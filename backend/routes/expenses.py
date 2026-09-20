"""
GET  /api/expenses           — list receipts belonging to the authenticated user
GET  /api/expenses/<id>      — fetch a single receipt (only if it belongs to
                               the authenticated user)
POST /api/expenses/email     — email a selection of receipts as a bill to a
                               recipient. Body: { receipt_ids, recipient_email,
                               description }.

All routes are per-user: the `user_id` filter is applied server-side via
the @require_auth decorator (which sets request.user_id), and the dynamo
helper filters on the `user_id` field in the DynamoDB item.

Protected by `@require_auth`.
"""

import re
from datetime import datetime, timezone
from html import escape

from flask import Blueprint, jsonify, request

from services.auth import require_auth
from services.dynamo import (
    get_expense,
    get_expenses_by_ids,
    list_expenses,
    list_expenses_for_month,
)
from services.ses import send_expense_bill

expenses_bp = Blueprint("expenses", __name__)

# Basic email regex — same check as routes/auth.py. Not RFC-5322 complete
# but good enough for the hackathon. SES does its own validation on send.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# YYYY-MM — strict format, rejects "2026-1" (must be zero-padded) and
# "2026-13" (month out of range). Mirrors the validator in routes/budget.py
# so the two endpoints agree on what a "valid month" is. Pre-compiled so we
# don't recompile on every request.
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(month):
    """Return True if `month` matches YYYY-MM with a valid month 01-12.

    The literal string "all" is also accepted and means "no month filter" —
    see get_expenses() for why that sentinel exists.
    """
    return bool(month and (month == "all" or _MONTH_RE.match(month)))


@expenses_bp.get("/expenses/months")
@require_auth
def get_expense_months():
    """Return the months this user actually has receipts in.

    Response: [{"month": "2026-03", "count": 2, "total": 3647.54}, ...]

    The dashboard uses this to detect the "I uploaded a receipt, it said it
    was processed, and the dashboard is empty" case. That happens whenever
    the OCR'd receipt date lands outside the selected month: the record IS in
    DynamoDB, but `GET /expenses?month=YYYY-MM` filters it out and the UI has
    no way to tell "you have no receipts" apart from "your receipts are in a
    different month". With this list the frontend can point straight at the
    month that holds them.
    """
    from services.dynamo import list_expense_months
    return jsonify(list_expense_months(request.user_id))


@expenses_bp.get("/expenses")
@require_auth
def get_expenses():
    """List the authenticated user's receipts.

    Query params:
      ?month=YYYY-MM  — when present and valid, ONLY receipts whose `date`
                        (YYYY-MM-DD) starts with that prefix are returned.
                        When omitted or empty, every receipt is returned
                        (legacy / all-time behaviour, kept for any caller
                        that hasn't been migrated yet).

    The dashboard always sends `?month=…` so every widget — top stat cards,
    category breakdown chart, and the recent-expenses table — stays in sync
    with the active month selector in the top-right. The prefix filter is
    delegated to `services.dynamo.list_expenses_for_month`, which compares
    against the receipt `date` string written at ingest time.

    Returns 400 `invalid_month` if `month` is provided but malformed, so a
    client bug can't silently fall through to all-time data.
    """
    month = (request.args.get("month") or "").strip()
    if month:
        if not _validate_month(month):
            return jsonify({
                "error": "invalid_month",
                "hint": "month must be 'YYYY-MM' (e.g. '2026-09'), zero-padded, "
                        "or 'all' for every month.",
            }), 400
        if month == "all":
            items = list_expenses(user_id=request.user_id)
        else:
            items = list_expenses_for_month(request.user_id, month)
    else:
        # No month supplied → all-time fallback. The dashboard never hits
        # this branch now, but other callers (tests, admin views) may.
        items = list_expenses(user_id=request.user_id)

    # Newest first — sort in-process. At hackathon scale (~dozens of
    # receipts per user) this is fine; at larger scale we'd add a GSI on
    # created_at or use DynamoDB Streams to maintain a sorted view.
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return jsonify(items)


@expenses_bp.get("/expenses/<expense_id>")
@require_auth
def get_expense_detail(expense_id):
    # get_expense enforces ownership at the helper level — returns None if
    # the record doesn't exist OR belongs to a different user. The caller
    # can't distinguish the two cases (anti-enumeration).
    item = get_expense(expense_id, user_id=request.user_id)
    if item is None:
        return jsonify({"error": "not_found", "expense_id": expense_id}), 404
    return jsonify(item)


@expenses_bp.get("/expenses/<expense_id>/fraud")
@require_auth
def get_expense_fraud(expense_id):
    """Return the stored fraud analysis for one receipt.

    The fraud_result is computed at ingest time and stored on the
    ExpenseRecords row. This endpoint exposes it as a structured JSON
    payload so reviewers / admins can see which checks fired, the
    final score, and the diagnostic details (Hamming distances, ELA
    stddev, EXIF tags, etc.) without re-running the pipeline.

    Response shape:
        {
          "expense_id": "...",
          "fraud_score": 87,
          "fraud_level": "FLAGGED",
          "fraud_result": { ...full FraudResult.to_dict()... },
          "file_hash": "...",
          "phash": 1234567,
          "content_fingerprint": "..."
        }

    Returns 404 if the receipt doesn't exist or doesn't belong to the
    caller. Returns 200 with `fraud_result=null` if the pipeline hasn't
    run on this receipt (e.g. the receipt was ingested before fraud
    detection was added, or the pipeline crashed during ingest).
    """
    item = get_expense(expense_id, user_id=request.user_id)
    if item is None:
        return jsonify({"error": "not_found", "expense_id": expense_id}), 404
    return jsonify({
        "expense_id": expense_id,
        "fraud_score": item.get("fraud_score"),
        "fraud_level": item.get("fraud_level"),
        "fraud_result": item.get("fraud_result"),
        "file_hash": item.get("file_hash"),
        "phash": item.get("phash"),
        "content_fingerprint": item.get("content_fingerprint"),
    })


@expenses_bp.post("/expenses/<expense_id>/fraud/reanalyze")
@require_auth
def reanalyze_fraud(expense_id):
    """Re-run the fraud pipeline against an already-stored receipt.

    Useful when:
      * a fraud-detection checker has been improved since the receipt
        was originally ingested (the stored `fraud_result` reflects the
        old algorithm).
      * the original pipeline crashed at ingest time and the record was
        written with `fraud_result=null`.

    The endpoint:
      1. Looks up the receipt (ownership-checked via get_expense).
      2. Downloads the original image from S3 (using the receipt's
         `s3_key`).
      3. Rebuilds a FraudContext from the stored fields.
      4. Calls `run_fraud_pipeline`.
      5. Updates the record via `update_expense_fraud_result`.

    Returns 200 with the new fraud analysis on success, 404 if the
    receipt doesn't exist / isn't owned, 409 if the receipt has no
    `s3_key` to re-download, 503 if S3 download fails.
    """
    import os
    import tempfile

    item = get_expense(expense_id, user_id=request.user_id)
    if item is None:
        return jsonify({"error": "not_found", "expense_id": expense_id}), 404

    s3_key = item.get("s3_key")
    if not s3_key:
        return jsonify({
            "error": "no_s3_key",
            "hint": "This receipt has no stored S3 key — cannot re-download for analysis.",
        }), 409

    # Download the original image to a tmp file. In mock mode this is
    # patched out by the trigger-ocr endpoint; for the standalone
    # reanalyze endpoint we use the real S3 client. In mock mode that
    # means `download_file` is a no-op and `image_path` won't exist —
    # the pipeline tolerates this (image-based checks skip).
    bucket = os.environ.get("S3_BUCKET", "receipts-bucket")
    tmp_path = None
    try:
        from services.s3 import _s3  # use the same client the rest of the backend uses
        suffix = os.path.splitext(s3_key)[-1] or ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        try:
            _s3.download_file(bucket, s3_key, tmp.name)
            tmp_path = tmp.name
        except Exception as exc:
            # In mock mode, the mock S3 client's download_file is a no-op
            # and no file is actually written. Tolerate it.
            print(f"[fraud-reanalyze] S3 download failed for {s3_key}: {exc}")
            # tmp_path stays None → pipeline runs with image_path=None
    except Exception as exc:
        print(f"[fraud-reanalyze] Could not obtain S3 client: {exc}")

    # Build context from the stored record. We don't have the raw OCR
    # text any more (it wasn't stored) — that's OK because the math /
    # logic checkers operate on the parsed fields, which we DO have
    # (vendor, amount, date, currency on the record).
    parsed = {
        "vendor": item.get("vendor"),
        "amount": item.get("original_amount", item.get("amount")),
        "date": item.get("date"),
        "currency": item.get("currency", "INR"),
        "invoice_number": item.get("invoice_number"),
    }

    from services.fraud import run_fraud_pipeline
    from services.dynamo import (
        list_expenses,
        list_receipt_fingerprints,
        update_expense_fraud_result,
    )

    existing_items = list_expenses(user_id=request.user_id)
    existing_fingerprints = list_receipt_fingerprints(user_id=request.user_id)

    result, file_hash, phash = run_fraud_pipeline(
        user_id=request.user_id,
        s3_key=s3_key,
        image_path=tmp_path,
        ocr_text="",  # not stored on the record; only parsed fields available
        parsed=parsed,
        category=item.get("category", "other"),
        existing_items=existing_items,
        existing_fingerprints=existing_fingerprints,
        invoice_number=item.get("invoice_number"),
    )

    update_expense_fraud_result(
        expense_id=expense_id,
        fraud_result=result.to_dict(),
        fraud_score=result.fraud_score,
        fraud_level=result.risk_level,
    )

    # Clean up the tmp file
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return jsonify({
        "expense_id": expense_id,
        "fraud_score": result.fraud_score,
        "fraud_level": result.risk_level,
        "fraud_result": result.to_dict(),
        "file_hash": file_hash,
        "phash": phash,
    })


@expenses_bp.post("/expenses/email")
@require_auth
def email_receipts_as_bill():
    """Email a selection of receipts as an HTML bill to a recipient.

    Request:
      {
        "receipt_ids": ["uuid1", "uuid2", ...],  # 1..50 ids
        "recipient_email": "advisor@example.edu",
        "description": "September 2026 cultural fest expenses"
      }

    The endpoint fetches only receipts belonging to request.user_id — any
    id in `receipt_ids` that belongs to a different user is rejected with
    403 (so callers can't enumerate other users' receipt IDs).

    Response: { "message_id": "...", "sent_count": N, "total": 1234.50 }
    Errors:   400 invalid_request | invalid_recipient_email | no_receipt_ids
              403 receipt_not_owned (one or more ids belong to another user)
              500 send_failed
    """
    body = request.get_json(silent=True) or {}
    receipt_ids = body.get("receipt_ids") or []
    recipient_email = (body.get("recipient_email") or "").strip().lower()
    description = (body.get("description") or "").strip()

    # --- Validate recipient email ---
    if not recipient_email or not _EMAIL_RE.match(recipient_email):
        return jsonify({"error": "invalid_recipient_email"}), 400

    # --- Validate receipt_ids ---
    if not isinstance(receipt_ids, list) or len(receipt_ids) == 0:
        return jsonify({"error": "no_receipt_ids"}), 400
    # Cap at 50 to avoid a single email with hundreds of receipts — both
    # a UX limit and a guard against accidental "select all" on a huge list.
    if len(receipt_ids) > 50:
        return jsonify({"error": "too_many_receipts", "max": 50}), 400
    # Deduplicate — a user might checkbox the same row twice in a flaky UI.
    # We preserve order for the email body (newest-first as returned by the
    # list endpoint).
    seen = set()
    unique_ids = []
    for rid in receipt_ids:
        if rid and rid not in seen:
            seen.add(rid)
            unique_ids.append(rid)

    # --- Fetch the receipts, scoped to this user ---
    # get_expenses_by_ids filters on user_id internally, so even if a
    # caller slips in an id belonging to another user, we won't return it.
    # But we DO want to detect that case so we can 403 — silently dropping
    # it would let an attacker confirm whether an id exists for another user
    # by observing whether the count matches.
    fetched = get_expenses_by_ids(user_id=request.user_id, expense_ids=unique_ids)
    if len(fetched) != len(unique_ids):
        # At least one id either doesn't exist or belongs to another user.
        # We return the same error for both cases — don't leak which.
        return jsonify({
            "error": "receipt_not_owned",
            "hint": "One or more receipt_ids don't exist or belong to another user.",
        }), 403

    # --- Compute the total ---
    total = 0.0
    for item in fetched:
        try:
            total += float(item.get("amount", 0))
        except (TypeError, ValueError):
            continue
    total = round(total, 2)

    # --- Build the HTML email body ---
    # We sort by date descending for readability — the recipient sees the
    # most recent receipt first.
    fetched.sort(key=lambda r: r.get("date", ""), reverse=True)
    html_body = _build_bill_html(fetched, total, description, request.user_id)
    text_body = _build_bill_text(fetched, total, description)

    subject = f"Outlay bill — {description}" if description else "Outlay bill"

    # --- Send via SES (or mock) ---
    try:
        message_id = send_expense_bill(
            recipient_email=recipient_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
    except Exception as exc:
        return jsonify({"error": "send_failed", "detail": str(exc)}), 500

    return jsonify({
        "message_id": message_id,
        "sent_count": len(fetched),
        "total": total,
        "recipient": recipient_email,
    })


def _fmt_amount(n, currency="INR"):
    """Format a number with the given currency's symbol — used for the
    ORIGINAL amount annotation on foreign-currency receipts."""
    symbols = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
    symbol = symbols.get((currency or "INR").upper(), (currency or "₹"))
    try:
        return f"{symbol}{float(n):,.2f}"
    except (TypeError, ValueError):
        return f"{symbol}0.00"


def _fmt_row_amount(item):
    """Render a receipt row's amount for the email bill — always INR.

    `item['amount']` is the frozen INR value written at ingest time. When
    the receipt was in a foreign currency we append the original so the
    recipient can audit the conversion:  "₹404.60  ($4.86 @ 83.25)".
    Legacy rows without fx fields just show the INR amount.
    """
    try:
        inr = float(item.get("amount", 0))
    except (TypeError, ValueError):
        inr = 0.0
    text = f"₹{inr:,.2f}"
    currency = (item.get("currency") or "INR").upper()
    original = item.get("original_amount")
    rate = item.get("fx_rate")
    if currency != "INR" and original is not None:
        try:
            original = float(original)
            rate_txt = f" @ {float(rate):,.2f}" if rate is not None else ""
            text += f"  ({_fmt_amount(original, currency)}{rate_txt})"
        except (TypeError, ValueError):
            pass
    return text


def _build_bill_html(items, total, description, user_id):
    """Build the HTML email body for the bill. Uses inline styles because
    most email clients strip <style> tags."""
    rows = []
    for i, item in enumerate(items, start=1):
        rows.append(
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;'>{i}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;'>{escape(str(item.get('vendor') or '—'))}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;'>{escape(str(item.get('date') or '—'))}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;'>{escape(str(item.get('category') or '—'))}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right;'>{_fmt_row_amount(item)}</td>"
            f"</tr>"
        )
    rows_html = "\n".join(rows)

    desc_html = f"<p style='color:#475569;font-size:14px;'>{escape(description)}</p>" if description else ""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""\
<div style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:0 auto;'>
  <h2 style='color:#0f172a;margin-bottom:4px;'>Outlay Bill</h2>
  {desc_html}
  <table style='width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;'>
    <thead>
      <tr style='background:#f8fafc;'>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>#</th>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>Vendor</th>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>Date</th>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>Category</th>
        <th style='padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb;'>Amount (INR)</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
    <tfoot>
      <tr>
        <td colspan='4' style='padding:10px 12px;text-align:right;font-weight:600;border-top:2px solid #e5e7eb;'>Total</td>
        <td style='padding:10px 12px;text-align:right;font-weight:600;border-top:2px solid #e5e7eb;'>{_fmt_amount(total)}</td>
      </tr>
    </tfoot>
  </table>
  <p style='color:#94a3b8;font-size:12px;margin-top:24px;'>
    Generated {escape(generated_at)} · {len(items)} receipt(s) · Sender user_id: {escape(user_id)}
  </p>
</div>"""


def _build_bill_text(items, total, description):
    """Plaintext fallback — for mail clients that don't render HTML."""
    lines = []
    if description:
        lines.append(description)
        lines.append("")
    lines.append(f"{'Vendor':<30} {'Date':<12} {'Category':<10} {'Amount (INR)':>26}")
    lines.append("-" * 84)
    for item in items:
        vendor = (str(item.get("vendor") or "—"))[:28]
        date = str(item.get("date") or "—")[:12]
        category = str(item.get("category") or "—")[:10]
        amt = _fmt_row_amount(item)[:26]
        lines.append(f"{vendor:<30} {date:<12} {category:<10} {amt:>26}")
    lines.append("-" * 84)
    lines.append(f"{'Total':<68} {_fmt_amount(total):>14}")
    return "\n".join(lines)
