"""Mathematical validation of receipt totals.

Given the parsed receipt data, this check verifies that the line items
add up to the claimed subtotal, that subtotal + tax + fees − discount
= grand total, and that the per-item amount = qty × unit_price.

Source of numbers
----------------
Two layers of data feed the math check:

  1. **`parsed` dict** from `parse_ocr_text(ocr_text)` — has `vendor`,
     `amount`, `date`, `currency`. The `amount` is what OCR thinks the
     grand total is (extracted via the tier-1 keyword search in
     `parse_ocr.py:_extract_amount`).

  2. **`line_items`** (optional) — a list of `{description, qty,
     unit_price, amount}` dicts. The current OCR parser doesn't
     expose these (it only returns the grand total), but the field is
     plumbed through `FraudContext` so future OCR enrichment (Textract,
     a structured parser, or even manual user entry) can supply them.

Tolerance
---------
Real-world receipts have rounding (cash transactions round to the
nearest ₹1, half-rupee rounding is rare, etc.). We accept:

  * Subtotal drift ≤ ₹1 absolute AND ≤ 0.5% relative → rounding-only
    (LOW signal, weight 5)
  * Subtotal drift > ₹1 absolute OR > 0.5% relative → inconsistency
    (HIGH signal, weight 35)
  * Grand total drift > ₹2 absolute OR > 1% relative → inconsistency

These tolerances are deliberately loose — the spec says "Rounding
differences within a reasonable tolerance". Tighter tolerances would
generate false positives on receipts where OCR mis-read a single digit.

Edge cases
----------
  * No line items → skip the per-item and subtotal checks; only the
    "total > 0" check runs (which is actually in `logic_check.py`,
    not here).
  * Line items without `qty` or `unit_price` → only check the
    per-line `amount` (we can't verify qty*price). Treat the
    parsed line as authoritative.
  * All-zero line items + zero total → not a math failure, that's a
    logic failure (non-positive total). Handled in `logic_check.py`.
"""

from typing import Any, Dict, List, Optional

from .context import FraudContext
from .result import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    fail,
    pass_,
    severity_rank,
)

# Tolerances. All amounts are in the receipt's ORIGINAL currency (we
# don't check the FX-converted amount because the conversion is
# already a lossy operation).
ABS_TOL_INR = 1.0          # ≤₹1 absolute drift = rounding
ABS_TOL_GRAND_INR = 2.0    # ≤₹2 absolute drift on grand total
REL_TOL = 0.005            # ≤0.5% relative drift = rounding
REL_TOL_GRAND = 0.01      # ≤1% relative drift on grand total


def _to_float(v, default: float = 0.0) -> float:
    """Defensive numeric coercion."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _normalize_line_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Pull qty / unit_price / amount out of a line-item dict,
    coercing to floats. Missing fields stay as None."""
    out = {"description": str(raw.get("description") or raw.get("name") or "")}
    if "qty" in raw or "quantity" in raw:
        out["qty"] = _to_float(raw.get("qty", raw.get("quantity")))
    if "unit_price" in raw or "price" in raw:
        out["unit_price"] = _to_float(raw.get("unit_price", raw.get("price")))
    out["amount"] = _to_float(raw.get("amount"))
    return out


def check_math(ctx: FraudContext) -> "CheckResult":
    """Verify that receipt totals reconcile.

    Skips when there are no line items (the OCR parser doesn't extract
    them yet — see module docstring). When skipped, returns a passing
    result with `details.skip_reason="no_line_items"`.
    """
    details: Dict[str, Any] = {}

    # The grand total is the parsed `amount`. Note: this is the
    # *original* amount (pre-FX), not the INR-converted amount, because
    # the check is about the receipt's internal arithmetic, not the FX
    # conversion.
    grand_total = ctx.original_amount
    details["grand_total"] = grand_total

    line_items_raw = ctx.line_items or []
    if not line_items_raw:
        # Nothing to validate arithmetically — the per-line / subtotal
        # checks need line items. Skipping is correct, not a cop-out:
        # we genuinely don't have the inputs to do the check.
        return pass_("math_validation", {
            **details,
            "skip_reason": "no_line_items",
            "note": "OCR parser did not expose line items; only the grand total was extracted",
        })

    # Normalize line items once.
    line_items = [_normalize_line_item(li) for li in line_items_raw]
    details["line_items"] = line_items

    failures: List[str] = []
    worst_weight_key: Optional[str] = None
    worst_severity = SEVERITY_LOW  # default to low (rounding-only)
    worst_severity_rank = severity_rank(SEVERITY_LOW)

    # ─── 1. Per-line: qty × unit_price = amount ────────────────────
    for i, li in enumerate(line_items):
        qty = li.get("qty")
        up = li.get("unit_price")
        amt = li.get("amount", 0.0)
        if qty is None or up is None:
            # Can't verify qty*price for this line — skip it, don't fail.
            continue
        expected = qty * up
        drift = abs(expected - amt)
        # Use a tighter absolute tolerance on line items (₹0.5) and
        # the standard relative tolerance.
        if drift > max(0.5, REL_TOL * max(abs(expected), abs(amt), 1.0)):
            failures.append(
                f"Line {i+1} ({li.get('description','')[:40]}): "
                f"{qty} × {up} = {expected:.2f} but amount is {amt:.2f}"
            )
            if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                worst_weight_key = "math_inconsistency_high"
                worst_severity = SEVERITY_HIGH
                worst_severity_rank = severity_rank(SEVERITY_HIGH)

    # ─── 2. Subtotal = sum of line items ──────────────────────────
    line_sum = sum(li.get("amount", 0.0) for li in line_items)
    details["line_sum"] = round(line_sum, 2)

    # `ctx.parsed` doesn't currently expose a `subtotal` — the parser
    # only extracts the grand total. If a future parser / enrichment
    # adds `subtotal` to the parsed dict, use it; otherwise treat the
    # line sum as the subtotal and compare to grand_total below.
    parsed_subtotal = _to_float(ctx.parsed.get("subtotal"))
    if parsed_subtotal:
        details["parsed_subtotal"] = parsed_subtotal
        drift = abs(line_sum - parsed_subtotal)
        rel = drift / max(abs(parsed_subtotal), 1.0)
        if drift > ABS_TOL_INR or rel > REL_TOL:
            failures.append(
                f"Sum of line items ({line_sum:.2f}) does not match parsed "
                f"subtotal ({parsed_subtotal:.2f})"
            )
            if drift > ABS_TOL_INR * 2 or rel > REL_TOL * 3:
                if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                    worst_weight_key = "math_inconsistency_high"
                    worst_severity = SEVERITY_HIGH
                    worst_severity_rank = severity_rank(SEVERITY_HIGH)
            else:
                if worst_severity_rank < severity_rank(SEVERITY_LOW):
                    worst_weight_key = "math_inconsistency_low"
                    worst_severity = SEVERITY_LOW
                    worst_severity_rank = severity_rank(SEVERITY_LOW)

    # ─── 3. Grand total = subtotal + tax - discount + fees ─────────
    # Pull these from the parsed dict when present (future parser
    # enrichment). Currently always None — the check skips silently.
    tax = _to_float(ctx.parsed.get("tax"))
    discount = _to_float(ctx.parsed.get("discount"))
    fees = _to_float(ctx.parsed.get("fees"))
    subtotal_for_grand = parsed_subtotal or line_sum
    expected_grand = subtotal_for_grand + tax - discount + fees
    details["expected_grand_total"] = round(expected_grand, 2)

    # Only run this check if at least one of tax/discount/fees was
    # actually parsed — otherwise we're just comparing grand_total to
    # itself.
    if any(ctx.parsed.get(k) is not None for k in ("tax", "discount", "fees")):
        drift = abs(expected_grand - grand_total)
        rel = drift / max(abs(grand_total), 1.0)
        if drift > ABS_TOL_GRAND_INR or rel > REL_TOL_GRAND:
            failures.append(
                f"Subtotal + tax - discount + fees = {expected_grand:.2f} "
                f"but grand total is {grand_total:.2f}"
            )
            if drift > ABS_TOL_GRAND_INR * 3 or rel > REL_TOL_GRAND * 3:
                if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                    worst_weight_key = "math_inconsistency_high"
                    worst_severity = SEVERITY_HIGH
                    worst_severity_rank = severity_rank(SEVERITY_HIGH)
            else:
                if worst_severity_rank < severity_rank(SEVERITY_LOW):
                    worst_weight_key = "math_inconsistency_low"
                    worst_severity = SEVERITY_LOW
                    worst_severity_rank = severity_rank(SEVERITY_LOW)
    else:
        # No tax/discount/fees parsed — directly compare the sum of
        # line items to the claimed grand total. This is the most
        # common case in practice (the current OCR parser only
        # extracts the grand total, not tax/discount/fees), so without
        # this branch a receipt where line items sum to ₹99.99 but
        # the total claims ₹800 would silently pass.
        #
        # We allow the same ₹2 absolute / 1% relative tolerance as
        # the explicit-tax branch — receipts with cash rounding to
        # the nearest rupee are common in India.
        drift = abs(line_sum - grand_total)
        rel = drift / max(abs(grand_total), 1.0)
        if drift > ABS_TOL_GRAND_INR or rel > REL_TOL_GRAND:
            failures.append(
                f"Sum of line items ({line_sum:.2f}) does not match grand total "
                f"({grand_total:.2f})"
            )
            if drift > ABS_TOL_GRAND_INR * 3 or rel > REL_TOL_GRAND * 3:
                if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                    worst_weight_key = "math_inconsistency_high"
                    worst_severity = SEVERITY_HIGH
                    worst_severity_rank = severity_rank(SEVERITY_HIGH)
            else:
                if worst_severity_rank < severity_rank(SEVERITY_LOW):
                    worst_weight_key = "math_inconsistency_low"
                    worst_severity = SEVERITY_LOW
                    worst_severity_rank = severity_rank(SEVERITY_LOW)

    if failures:
        # Determine final weight key from worst severity. Use
        # `worst_severity_rank` (numeric) rather than `worst_severity`
        # (string) — comparing severity strings directly with `>=`
        # does a lexicographic comparison, and `"low" >= "high"` is
        # True (because 'l' > 'h' alphabetically). That would make
        # EVERY math failure — even a ₹0.50 rounding drift — score
        # as HIGH (35 points), pushing legitimate receipts into
        # REVIEW/FLAGGED. The `worst_severity_rank` is already
        # maintained correctly above; we just need to actually use it.
        if worst_severity_rank >= severity_rank(SEVERITY_HIGH):
            weight_key = "math_inconsistency_high"
            severity = SEVERITY_HIGH
            reason = "Invoice total does not match calculated total"
        else:
            weight_key = "math_inconsistency_low"
            severity = SEVERITY_LOW
            reason = "Invoice total has minor rounding drift (within tolerance)"
        return fail(
            name="math_validation",
            weight_key=weight_key,
            severity=severity,
            reason=reason,
            details={**details, "failures": failures},
        )

    return pass_("math_validation", details)
