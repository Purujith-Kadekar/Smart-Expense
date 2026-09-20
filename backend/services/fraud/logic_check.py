"""Business-logic validation of receipt data.

These are common-sense checks: a receipt dated in the future is
impossible; a non-positive total is nonsensical; a GSTIN should match
the Indian format; an invoice number that's been seen before is
suspicious.

Each check is independent; we combine them into one CheckResult so
the pipeline sees one `logic_validation` entry in `checks`. If multiple
fail, we report the most severe.
"""

import re
from datetime import date as date_cls, datetime
from typing import Any, Dict, List, Optional, Tuple

from .context import FraudContext
from .result import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    fail,
    pass_,
)

# ──────────────────────────────────────────────────────────────────────
# Format validators
# ──────────────────────────────────────────────────────────────────────
# Indian GSTIN: 2 state code + 10 chars PAN + 1 entity + 1 Z + 1 checksum.
# Regex is deliberately loose — we'd rather flag than block. Tightening
# this would require implementing the GST checksum (modulo-36), which is
# overkill for a soft fraud signal.
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{3}$")

# Indian phone numbers — 10 digits, optionally with +91 country code.
# Used to flag obvious garbage like "12345" presented as a phone.
_PHONE_RE = re.compile(r"^(\+91)?[6-9][0-9]{9}$")

# Invoice number — alphanumeric, 1-20 chars, may include /-_. We're
# only checking for *obvious garbage*, not enforcing any one format.
_INVOICE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-/_.]{0,19}$", re.IGNORECASE)


def _normalize_amount(a) -> float:
    try:
        return float(a or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_future(d: date_cls, ref: datetime) -> bool:
    """True if `d` is strictly after `ref` (timezone-aware datetime)."""
    if d is None:
        return False
    ref_date = ref.date()
    return d > ref_date


def _parse_iso_date(s: str) -> Optional[date_cls]:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_invoice_number(s: Optional[str]) -> Optional[str]:
    """Strip whitespace + uppercase. Return None for empty/garbage."""
    if not s:
        return None
    s2 = str(s).strip().upper()
    return s2 or None


def _check_reused_invoice_number(ctx: FraudContext) -> Tuple[bool, str, Dict[str, Any]]:
    """Look for `invoice_number` already used by another receipt."""
    inv = _normalize_invoice_number(ctx.invoice_number)
    if not inv:
        return False, "", {}
    # Also check the parsed dict (some parsers put invoice_number there).
    parsed_inv = _normalize_invoice_number(ctx.parsed.get("invoice_number"))
    candidates = {inv}
    if parsed_inv:
        candidates.add(parsed_inv)

    for prior in ctx.existing_items:
        if prior.get("s3_key") == ctx.s3_key:
            continue
        if prior.get("user_id") != ctx.user_id:
            continue
        prior_inv = _normalize_invoice_number(
            prior.get("invoice_number") or prior.get("invoice_no")
        )
        if prior_inv and prior_inv in candidates:
            return True, (
                f"Invoice number '{inv}' has been used previously "
                f"(on expense_id={prior.get('expense_id')})"
            ), {
                "invoice_number": inv,
                "matched_expense_id": prior.get("expense_id"),
                "matched_s3_key": prior.get("s3_key"),
            }
    return False, "", {}


def _check_gstin(ctx: FraudContext) -> Tuple[bool, str, Dict[str, Any]]:
    """Flag a GSTIN that doesn't match the Indian format."""
    g = ctx.gstin or ctx.parsed.get("gstin")
    if not g:
        # No GSTIN present — most small Indian receipts don't have one.
        # Not a signal either way.
        return False, "", {}
    g2 = str(g).strip().upper().replace(" ", "")
    if not _GSTIN_RE.match(g2):
        return True, (
            f"GSTIN '{g2}' does not match the standard Indian GSTIN format "
            f"(2 digits state code, 5 letters PAN, 4 digits, 1 letter, 3 alphanumeric)"
        ), {"gstin": g2}
    return False, "", {}


def _check_date_validity(ctx: FraudContext) -> Tuple[bool, str, str, Dict[str, Any]]:
    """Check the receipt date is valid and not in the future.

    Returns `(failed, weight_key, reason, details)`. `weight_key` is
    empty when the check passed; non-empty gives the failure weight.
    """
    if not ctx.receipt_date:
        # OCR didn't extract a date → this is a logic issue (the
        # receipt should have a date), but the OCR fallback at the
        # Lambda layer stamps `today` so `ctx.receipt_date` will rarely
        # be None. If it is, treat as a low-severity "no date" flag.
        return True, "logic_invalid_date", (
            "Receipt has no parseable date — date field is empty"
        ), {"receipt_date": None}
    if _is_future(ctx.receipt_date, ctx.uploaded_at):
        return True, "logic_future_date", (
            f"Receipt date {ctx.receipt_date.isoformat()} is in the future "
            f"(upload date: {ctx.uploaded_at.date().isoformat()})"
        ), {
            "receipt_date": ctx.receipt_date.isoformat(),
            "upload_date": ctx.uploaded_at.date().isoformat(),
        }
    return False, "", "", {}


def _check_amount(ctx: FraudContext) -> Tuple[bool, str, str, Dict[str, Any]]:
    """Total should be positive and reasonable."""
    amt = ctx.original_amount
    if amt <= 0:
        return True, "logic_non_positive_total", (
            f"Receipt total must be greater than zero (got {amt})"
        ), {"amount": amt}
    # Sanity ceiling: a single receipt > ₹10 lakh (~$12k) is almost
    # certainly an OCR misread. Don't reject — just flag.
    # (The number is deliberately high; we're looking for OCR errors,
    # not policing spending limits.)
    if amt > 1_000_000:
        return True, "logic_non_positive_total", (
            f"Receipt total {amt} is implausibly high (>₹10 lakh) — likely an OCR error"
        ), {"amount": amt}
    return False, "", "", {}


def _check_tax_consistency(ctx: FraudContext) -> Tuple[bool, str, str, Dict[str, Any]]:
    """If both taxable amount and tax % are known, verify the tax
    amount matches. Returns no signal when either is missing."""
    taxable = _to_float_or_none(ctx.parsed.get("taxable_amount"))
    tax_pct = _to_float_or_none(ctx.parsed.get("tax_percent"))
    tax_amount = _to_float_or_none(ctx.parsed.get("tax_amount"))
    if taxable is None or tax_pct is None or tax_amount is None:
        return False, "", "", {}
    expected_tax = taxable * tax_pct / 100
    drift = abs(expected_tax - tax_amount)
    rel = drift / max(abs(tax_amount), 1.0)
    if drift > 1.0 or rel > 0.05:
        return True, "logic_tax_mismatch", (
            f"Tax amount {tax_amount} doesn't match {tax_pct}% of taxable {taxable} "
            f"(expected {expected_tax:.2f})"
        ), {
            "taxable_amount": taxable,
            "tax_percent": tax_pct,
            "tax_amount": tax_amount,
            "expected_tax": expected_tax,
        }
    return False, "", "", {}


def _to_float_or_none(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_logic(ctx: FraudContext) -> "CheckResult":
    """Run all logical validations. Returns the worst signal found."""
    failures: List[Tuple[str, str, str, Dict[str, Any]]] = []
    # (weight_key, severity, reason, details)
    _severity_for = {
        "logic_future_date": SEVERITY_MEDIUM,
        "logic_invalid_date": SEVERITY_HIGH,
        "logic_non_positive_total": SEVERITY_HIGH,
        "logic_reused_invoice_number": SEVERITY_HIGH,
        "logic_gstin_invalid": SEVERITY_LOW,
        "logic_tax_mismatch": SEVERITY_MEDIUM,
    }

    # Date
    failed, wk, reason, d = _check_date_validity(ctx)
    if failed:
        failures.append((wk, _severity_for[wk], reason, d))

    # Amount
    failed, wk, reason, d = _check_amount(ctx)
    if failed:
        failures.append((wk, _severity_for[wk], reason, d))

    # Invoice reuse
    failed, reason, d = _check_reused_invoice_number(ctx)
    if failed:
        failures.append((
            "logic_reused_invoice_number",
            _severity_for["logic_reused_invoice_number"],
            reason, d
        ))

    # GSTIN format
    failed, reason, d = _check_gstin(ctx)
    if failed:
        failures.append((
            "logic_gstin_invalid",
            _severity_for["logic_gstin_invalid"],
            reason, d
        ))

    # Tax consistency (no signal if inputs missing)
    failed, wk, reason, d = _check_tax_consistency(ctx)
    if failed:
        failures.append((wk, _severity_for[wk], reason, d))

    if not failures:
        return pass_("logic_validation", {
            "receipt_date": ctx.receipt_date.isoformat() if ctx.receipt_date else None,
            "amount": ctx.original_amount,
            "invoice_number": _normalize_invoice_number(ctx.invoice_number),
        })

    # Pick the worst by severity (CRITICAL > HIGH > MEDIUM > LOW > INFO).
    _rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    worst = max(failures, key=lambda f: _rank.get(f[1], 0))
    weight_key, severity, reason, details = worst

    all_failures = [
        {"weight_key": wk, "severity": sev, "reason": r, "details": det}
        for wk, sev, r, det in failures
    ]
    return fail(
        name="logic_validation",
        weight_key=weight_key,
        severity=severity,
        reason=reason,
        details={**details, "all_failures": all_failures},
    )
