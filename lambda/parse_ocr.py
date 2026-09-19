"""
OCR text parser for the Outlay ingestion Lambda.

Replaces the old Textract-structured parser with a regex-based parser
that extracts vendor / amount / date from raw OCR text (as returned by
pytesseract). This lets the Lambda run 100% offline — no AWS Textract
API call, no network, no billing.

The parser is intentionally lenient: receipts are messy, OCR is imperfect,
and a wrong value is better than a crash. Each field falls back to None
(or 0.0 for amount) if no match is found — the Lambda substitutes sensible
defaults.

Known limitations vs the old Textract parser:
  - Vendor detection is heuristic (first non-numeric line). Textract's
    structured VENDOR_NAME field was more accurate.
  - Amount detection looks for "total" / "grand total" / "amount due"
    keywords. Textract's labelled TOTAL field was more reliable.
  - Date detection covers the 3 most common formats. Textract's
    INVOICE_RECEIPT_DATE field handled more variants.

For a demo with clean printed receipts these heuristics work well. For
production with handwritten or crumpled receipts, you'd want Textract
or a ML model.
"""

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Amount parsing — strip currency symbols + commas, convert to float
# ---------------------------------------------------------------------------

def _parse_amount(raw):
    """Convert an amount string ('₹1,234.50', 'Rs. 999', '1234.5') to float.
    Returns 0.0 if it cannot parse."""
    if raw is None:
        return 0.0
    cleaned = (
        raw.replace(",", "")
        .replace("₹", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
        .strip()
    )
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Date normalisation — parse common formats, output ISO 8601 (YYYY-MM-DD)
# ---------------------------------------------------------------------------

def _normalise_date(raw):
    """Best-effort date normalisation to ISO 8601 (YYYY-MM-DD).
    Returns None if the date cannot be parsed."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# S3 key parsing — extracts user_id + category from the key path
# ---------------------------------------------------------------------------

# S3 key format (set by backend/routes/upload.py):
#   receipts/{user_id}/{category}/{uuid}_{filename}
#
# Lambda never talks to Flask, so the S3 key path is the only carrier for
# user_id and category from the browser to the Lambda. We parse them out
# here and stamp them onto the DynamoDB record.
_VALID_CATEGORIES = {"college", "mess", "event", "other"}


def parse_s3_key(s3_key):
    """Extract {user_id, category, filename} from an S3 object key.

    Expected format: receipts/{user_id}/{category}/{uuid}_{filename}

    Returns:
        dict with keys 'user_id', 'category', 'filename'. Any field that
        could not be parsed is set to None.

    >>> parse_s3_key("receipts/abc-123/college/uuid_receipt.jpg")
    {'user_id': 'abc-123', 'category': 'college', 'filename': 'uuid_receipt.jpg'}
    >>> parse_s3_key("receipts/abc-123/invalid/uuid_receipt.jpg")
    {'user_id': 'abc-123', 'category': None, 'filename': 'uuid_receipt.jpg'}
    >>> parse_s3_key("malformed-key")
    {'user_id': None, 'category': None, 'filename': None}
    """
    if not s3_key:
        return {"user_id": None, "category": None, "filename": None}

    parts = s3_key.split("/")
    if len(parts) < 4 or parts[0] != "receipts":
        return {"user_id": None, "category": None, "filename": None}

    user_id = parts[1] or None
    category = parts[2] if parts[2] in _VALID_CATEGORIES else None
    filename = "/".join(parts[3:]) or None

    return {"user_id": user_id, "category": category, "filename": filename}


# ---------------------------------------------------------------------------
# OCR text parsing — extract vendor / amount / date from raw text
# ---------------------------------------------------------------------------

# Regex patterns for the amount field, ordered by specificity. The first
# match wins. We look for "total" / "grand total" / "amount due" keywords
# followed by a currency-prefixed number, then fall back to any standalone
# currency amount in the text.
_AMOUNT_PATTERNS = [
    # "Grand Total: ₹1,234.50" or "GRAND TOTAL Rs. 1234" (most specific)
    re.compile(
        r"(?:grand\s*total|g\.?total)\s*[:\-]?\s*(?:rs\.?|₹|inr|\$|€|£)?\s*([\d,]+\.?\d*)",
        re.IGNORECASE,
    ),
    # "Total: 999.99" or "TOTAL AMOUNT ₹500" or "Amount Due: 1500"
    re.compile(
        r"(?:total\s*amount|amount\s*due|total|amt)\s*[:\-]?\s*(?:rs\.?|₹|inr|\$|€|£)?\s*([\d,]+\.?\d*)",
        re.IGNORECASE,
    ),
    # Standalone "₹1,234.50" or "Rs. 999" or "€2500" — last resort, picks the largest
    re.compile(
        r"(?:rs\.?|₹|inr|\$|€|£)\s*([\d,]+\.?\d*)",
        re.IGNORECASE,
    ),
]

# Date patterns — ISO, US, EU, dot-separated. We scan the full text and
# take the first match.
_DATE_PATTERNS = [
    re.compile(r"(\d{4}-\d{2}-\d{2})"),                    # 2026-09-14
    re.compile(r"(\d{1,2}/\d{1,2}/\d{4})"),                # 14/09/2026 or 09/14/2026
    re.compile(r"(\d{1,2}-\d{1,2}-\d{4})"),                # 14-09-2026
    re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})"),              # 14.09.2026
]


def parse_ocr_text(text):
    """Extract {vendor, amount, date} from raw OCR text.

    Args:
        text: The full string output of pytesseract.image_to_string().
              Typically 10-50 lines of messy text from a receipt photo.

    Returns:
        dict with keys 'vendor', 'amount', 'date'. Any field that could
        not be parsed is set to None (amount → 0.0), leaving the Lambda
        to substitute defaults.
    """
    if not text:
        return {"vendor": None, "amount": 0.0, "date": None}

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # --- Vendor: heuristic = first line that doesn't look like a date or
    # a standalone number. Receipts usually have the vendor name at the
    # top. We skip lines that are mostly digits (dates, amounts) and
    # lines that are too short (OCR artefacts). ---
    vendor = None
    for line in lines:
        # Skip lines that are mostly digits / punctuation (dates, amounts)
        alpha_ratio = sum(c.isalpha() for c in line) / max(len(line), 1)
        if alpha_ratio < 0.4:
            continue
        # Skip lines that look like dates
        if re.search(r"\d{2,4}[-/.]\d{1,2}[-/.]\d{2,4}", line):
            continue
        # Skip lines that are just a number
        if re.match(r"^[\d\s.,]+$", line):
            continue
        vendor = line
        break
    # Fallback: if no good line was found, use the first line as-is
    if vendor is None and lines:
        vendor = lines[0]

    # --- Amount: try each pattern in order of specificity. For the
    # standalone currency pattern (last fallback), pick the LARGEST
    # match — the total is usually the biggest number on a receipt. ---
    amount = 0.0
    for i, pattern in enumerate(_AMOUNT_PATTERNS):
        matches = pattern.findall(text)
        if not matches:
            continue
        if i == len(_AMOUNT_PATTERNS) - 1:
            # Last-resort standalone currency pattern — pick the largest.
            values = [_parse_amount(m) for m in matches]
            amount = max(values) if values else 0.0
        else:
            # Keyword patterns — take the first match (usually the most
            # specific, e.g. "Grand Total" before "Total").
            amount = _parse_amount(matches[0])
        if amount > 0:
            break

    # --- Date: take the first regex match in the full text. ---
    date_str = None
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            date_str = match.group(1)
            break
    date = _normalise_date(date_str) if date_str else None

    return {
        "vendor": (vendor or "").strip() or None,
        "amount": amount,
        "date": date,
    }
