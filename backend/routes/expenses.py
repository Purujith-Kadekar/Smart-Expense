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
from services.dynamo import get_expense, get_expenses_by_ids, list_expenses
from services.ses import send_expense_bill

expenses_bp = Blueprint("expenses", __name__)

# Basic email regex — same check as routes/auth.py. Not RFC-5322 complete
# but good enough for the hackathon. SES does its own validation on send.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@expenses_bp.get("/expenses")
@require_auth
def get_expenses():
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

    subject = f"Expense bill — {description}" if description else "Expense bill"

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


def _fmt_amount(n):
    """Format a number as ₹X,XXX.XX — consistent with the frontend."""
    try:
        return f"₹{float(n):,.2f}"
    except (TypeError, ValueError):
        return "₹0.00"


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
            f"<td style='padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right;'>{_fmt_amount(item.get('amount', 0))}</td>"
            f"</tr>"
        )
    rows_html = "\n".join(rows)

    desc_html = f"<p style='color:#475569;font-size:14px;'>{escape(description)}</p>" if description else ""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""\
<div style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:0 auto;'>
  <h2 style='color:#0f172a;margin-bottom:4px;'>Expense Bill</h2>
  {desc_html}
  <table style='width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;'>
    <thead>
      <tr style='background:#f8fafc;'>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>#</th>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>Vendor</th>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>Date</th>
        <th style='padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;'>Category</th>
        <th style='padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb;'>Amount</th>
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
    lines.append(f"{'Vendor':<30} {'Date':<12} {'Category':<10} {'Amount':>12}")
    lines.append("-" * 70)
    for item in items:
        vendor = (str(item.get("vendor") or "—"))[:28]
        date = str(item.get("date") or "—")[:12]
        category = str(item.get("category") or "—")[:10]
        lines.append(f"{vendor:<30} {date:<12} {category:<10} {_fmt_amount(item.get('amount', 0)):>12}")
    lines.append("-" * 70)
    lines.append(f"{'Total':<54} {_fmt_amount(total):>12}")
    return "\n".join(lines)
