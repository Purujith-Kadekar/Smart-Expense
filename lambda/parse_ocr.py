"""
OCR text parser for the Outlay ingestion Lambda.

Replaces the old Textract-structured parser with a regex-based parser
that extracts vendor / amount / date / currency from raw OCR text (as
returned by pytesseract or EasyOCR). This lets the Lambda run 100%
offline — no AWS Textract API call, no network, no billing.

The parser is intentionally lenient: receipts are messy, OCR is imperfect,
and a wrong value is better than a crash. Each field falls back to None
(or 0.0 for amount) if no match is found — the Lambda substitutes sensible
defaults.

Parsing strategy (v2 — rewritten after demo-day bug reports):

  AMOUNT  — line-based, bottom-up. Receipts print the grand total near the
            BOTTOM, above smaller components. We scan lines from the bottom,
            skipping "Sub Total" / tax / GST / qty lines, and take the
            largest number on the first keyword line we meet ("Grand
            Total" tier before plain "Total" tier). The old version ran a
            substring regex over the whole text and took the FIRST match —
            which matched the "Total" inside "Sub Total" and reported the
            subtotal. That bug is why receipts showed the pre-tax amount.

  DATE    — day-first (DD/MM/YYYY preferred, Indian receipts) with a
            MM/DD fallback when day-first is impossible (day > 12). The
            old version tried MM/DD BEFORE DD/MM, so "07/09/2026" (7 Sept)
            was stored as July 9 — landing the expense in the wrong month,
            which is why the budget / income-vs-spent charts never moved
            even though the expense list showed the receipt. We also
            prefer lines that mention date/invoice keywords and use
            boundary guards so an invoice number like "26-09-2026-4417"
            is never mistaken for a date.

  CURRENCY— scans the text for currency markers (₹/Rs/INR, $/USD, €/EUR,
            £/GBP, ¥/JPY) and returns the ISO code of the most frequent
            one. The old version stripped symbols without recording which
            currency it found, so a $4.86 receipt was displayed as ₹4.86.

  VENDOR  — unchanged heuristic: first line that is mostly letters and
            doesn't look like a date or a standalone number.
"""

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Currency detection
# ---------------------------------------------------------------------------

# Marker patterns per currency, ordered by detection priority. Each pattern
# is counted across the full text; the currency with the most hits wins.
# Ties resolve to the earlier entry in this list (INR first — Outlay).
_CURRENCY_MARKERS = [
    ("INR", [
        re.compile(r"₹"),
        re.compile(r"\brs\.?\s*\d", re.IGNORECASE),   # "Rs. 999" / "Rs999"
        re.compile(r"\binr\.?\s*\d", re.IGNORECASE),  # "INR 999" / "INR999"
        re.compile(r"\brupees\b", re.IGNORECASE),
    ]),
    ("USD", [
        re.compile(r"\$\s*\d"),
        re.compile(r"\busd\.?\s*\d", re.IGNORECASE),
        re.compile(r"\bdollars?\b", re.IGNORECASE),
    ]),
    ("EUR", [
        re.compile(r"€\s*\d"),
        re.compile(r"\beur\.?\s*\d", re.IGNORECASE),
        re.compile(r"\beuros?\b", re.IGNORECASE),
    ]),
    ("GBP", [
        re.compile(r"£\s*\d"),
        re.compile(r"\bgbp\.?\s*\d", re.IGNORECASE),
        re.compile(r"\bpounds?\b", re.IGNORECASE),
    ]),
    ("JPY", [
        re.compile(r"¥\s*\d"),
        re.compile(r"\bjpy\.?\s*\d", re.IGNORECASE),
        re.compile(r"\byen\b", re.IGNORECASE),
    ]),
]

_DEFAULT_CURRENCY = "INR"


def detect_currency(text):
    """Return the ISO-4217 code of the currency used in the receipt text.

    Counts marker occurrences per currency and picks the most frequent.
    Returns "INR" when nothing matches — this is an Indian expense
    app, so the prior is rupees.
    """
    if not text:
        return _DEFAULT_CURRENCY
    best_code, best_score = None, 0
    for code, patterns in _CURRENCY_MARKERS:
        score = sum(len(p.findall(text)) for p in patterns)
        if score > best_score:
            best_code, best_score = code, score
    return best_code or _DEFAULT_CURRENCY


# ---------------------------------------------------------------------------
# Amount parsing — strip currency symbols + commas, convert to float
# ---------------------------------------------------------------------------

def _parse_amount(raw):
    """Convert an amount string ('₹1,234.50', 'Rs. 999', '1234.5', '250/-',
    '€3,84') to float. Returns 0.0 if it cannot parse.

    Comma disambiguation when the token has commas but no dot:
      '1,234'     -> grouping comma  -> 1234
      '1,23,499'  -> Indian grouping -> 123499
      '3,84'      -> decimal comma   -> 3.84   (European receipts)
      '22,5'      -> decimal comma   -> 22.5
    Rule: exactly one comma followed by 1-2 digits is a decimal comma;
    anything else is a grouping comma and gets stripped.
    """
    if raw is None:
        return 0.0
    cleaned = (
        str(raw)
        .replace("₹", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("¥", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("RS", "")
        .replace("INR", "")
        .replace("USD", "")
        .replace("EUR", "")
        .replace("GBP", "")
        .replace("/-", "")
        .strip()
    )
    if "," in cleaned and "." not in cleaned:
        head, _, tail = cleaned.partition(",")
        rest = tail.replace(",", "")  # any further commas are grouping
        if len(tail) in (1, 2) and head.isdigit() and rest.isdigit():
            cleaned = f"{head}.{rest}"  # decimal comma, e.g. "3,84"
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Date normalisation — day-first (DD/MM/YYYY) with MM/DD fallback
# ---------------------------------------------------------------------------

_DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _valid_dmy(day, month, year):
    """True if (day, month, year) is a plausible calendar date.
    Year must be 2000-2100 (receipts, not medieval documents)."""
    if not (2000 <= year <= 2100):
        return False
    if not (1 <= month <= 12):
        return False
    if not (1 <= day <= _DAYS_IN_MONTH[month - 1]):
        return False
    # Reject Feb 30; allow Feb 29 only on leap years.
    if month == 2 and day == 29 and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return False
    return True


def _expand_year(y):
    """Expand a 2-digit year to 4 digits: 26 -> 2026, 98 -> 1998."""
    if y >= 100:
        return y
    return 2000 + y if y <= 68 else 1900 + y


def _normalise_date(raw):
    """Best-effort date normalisation to ISO 8601 (YYYY-MM-DD).

    Day-first: DD/MM/YYYY is tried BEFORE MM/DD/YYYY because Indian
    receipts print day-first. When day-first is impossible (first number
    > 12), we fall back to month-first (US receipts). ISO (YYYY-MM-DD)
    is unambiguous and checked first.

    Returns None if the date cannot be parsed.
    """
    if not raw:
        return None
    token = str(raw).strip()
    parts = re.split(r"[-/.]", token)
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        # Try the classic strptime formats for anything unusual.
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(token, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    a, b, c = (int(p) for p in parts)

    # ISO-style: year first (4-digit leading component).
    if len(parts[0]) == 4:
        year, month, day = _expand_year(a), b, c
        if _valid_dmy(day, month, year):
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    # Day-first (Indian default): DD/MM/[YY]YY
    day, month, year = a, b, _expand_year(c)
    if _valid_dmy(day, month, year):
        return f"{year:04d}-{month:02d}-{day:02d}"

    # Month-first fallback (US): MM/DD/[YY]YY
    month, day, year = a, b, _expand_year(c)
    if _valid_dmy(day, month, year):
        return f"{year:04d}-{month:02d}-{day:02d}"

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
# OCR text parsing — extract vendor / amount / date / currency from raw text
# ---------------------------------------------------------------------------

# Tier 1: strongest "this is the final payable amount" keywords.
_TOTAL_TIER1 = re.compile(
    r"grand\s*total|net\s*payable|amount\s*payable|total\s*payable|"
    r"total\s*due|balance\s*due|net\s*total|amount\s*due|net\s*amount|"
    r"total\s*amount|\btendered\b",
    re.IGNORECASE,
)
# Tier 2: weaker keywords — checked only when no tier-1 line exists.
_TOTAL_TIER2 = re.compile(r"\btotal\b|\bamount\b|\bamt\b|\bpayable\b", re.IGNORECASE)

# Lines that must NEVER be treated as the grand total. "Sub Total" is the
# headline bug: the substring "total" appears inside it, so a naive regex
# matches it. Also exclude tax components, item counts and savings rows.
_NON_TOTAL_LINE = re.compile(
    r"sub[\s\-]*total|sub\s*total|taxable|cgst|sgst|igst|\bgst\b|\bvat\b|"
    r"service\s*tax|round(?:ing)?\s*off|round\s*off|\bchange\b|\bcash\b|"
    r"total\s*(?:items?|qty|quantity|pcs|pieces|count|bill)|(?:items?|qty|quantity)\s*total|"
    r"sav(?:ings?|ed)|\bpoints\b|\bdiscount\b|tender\s*amount|in\s*words|"
    r"previous|balance\s*forward|due\s*amount\s*words",
    re.IGNORECASE,
)

# A standalone number token: digits with optional grouping commas and an
# optional decimal part. "105", "1,234.50", "1234.5".
_NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Currency-marked standalone amounts — used as a fallback when no keyword
# line is found. The total is usually the largest currency-marked number.
_CURRENCY_AMOUNT = re.compile(
    r"(?:rs\.?|₹|inr|usd|\$|eur|€|gbp|£|jpy|¥)\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Date-token regex with boundary guards. The lookarounds reject tokens
# embedded inside longer digit runs (invoice numbers like "26-09-2026-4417",
# phone numbers like "91-98765-43210"), which the old first-match regex
# happily mistook for dates.
_DATE_TOKEN = re.compile(
    r"(?<![\d\-/.])(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})(?![\d\-/.])"
)

# Lines that likely carry the transaction date. Scanned first, top-to-bottom.
_DATE_CONTEXT = re.compile(
    r"\bdate[d]?\b|\bdt\b|bill\s*date|invoice\s*date|\bbill\s*no\b|\binvoice\s*no\b|"
    r"\breceipt\b|\bcounter\b",
    re.IGNORECASE,
)


def _extract_amount(lines, text):
    """Line-based, bottom-up total extraction.

    Receipts print the grand total near the bottom; components (sub total,
    taxes) sit above it. Scanning bottom-up means we naturally hit "Grand
    Total" before "Total" before "Sub Total", even though all three contain
    the substring "total".

    On a keyword line we take the LARGEST number token: the total is the
    biggest number on its own line, and this survives trailing noise like
    "TOTAL 105.00 (5% GST INCL.)".
    """
    # Tier 1 then tier 2, both bottom-up.
    for tier in (_TOTAL_TIER1, _TOTAL_TIER2):
        for line in reversed(lines):
            if _NON_TOTAL_LINE.search(line):
                continue
            if not tier.search(line):
                continue
            values = [_parse_amount(m) for m in _NUMBER_TOKEN.findall(line)]
            values = [v for v in values if v > 0]
            if values:
                return max(values)

    # Fallback 1: largest currency-marked amount anywhere in the text.
    marked = [_parse_amount(m) for m in _CURRENCY_AMOUNT.findall(text)]
    marked = [v for v in marked if v > 0]
    if marked:
        return max(marked)

    # Fallback 2: largest number among the last few lines. The total row is
    # at the bottom, so this is a tighter (safer) net than "largest number
    # anywhere", which would happily return a phone number from the header.
    tail = [line for line in lines if line.strip()][-3:]
    tail_values = []
    for line in tail:
        tail_values.extend(v for v in (_parse_amount(m) for m in _NUMBER_TOKEN.findall(line)) if v > 0)
    if tail_values:
        return max(tail_values)

    return 0.0


def _extract_date(lines, text):
    """Extract the receipt date as ISO 8601, day-first.

    Preference order:
      1. Lines mentioning date/invoice keywords (top-to-bottom) — a real
         "Date: 03/09/2026" line beats an invoice number that merely looks
         date-ish.
      2. Any line, top-to-bottom.

    Boundary guards in _DATE_TOKEN reject tokens glued into longer digit
    runs. Every candidate is validated by _normalise_date (day-first).
    """
    for candidate_lines in (lines,):  # single pass structure kept for clarity
        for line in candidate_lines:
            if not _DATE_CONTEXT.search(line):
                continue
            for match in _DATE_TOKEN.finditer(line):
                date = _normalise_date(match.group(0))
                if date:
                    return date
    # No keyword-context line yielded a date — take the first valid token
    # from any line, top-to-bottom (receipt dates are near the top).
    for match in _DATE_TOKEN.finditer(text):
        date = _normalise_date(match.group(0))
        if date:
            return date
    return None


def parse_ocr_text(text):
    """Extract {vendor, amount, date, currency} from raw OCR text.

    Args:
        text: The full string output of pytesseract.image_to_string() or
              EasyOCR's newline-joined lines. Typically 10-50 lines of
              messy text from a receipt photo.

    Returns:
        dict with keys 'vendor', 'amount', 'date', 'currency'. Fields that
        cannot be parsed are set to None (amount -> 0.0, currency -> None),
        leaving the Lambda to substitute defaults.
    """
    if not text:
        return {"vendor": None, "amount": 0.0, "date": None, "currency": None}

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # --- Vendor: first line that is mostly letters and not a date/number ---
    vendor = None
    for line in lines:
        alpha_ratio = sum(c.isalpha() for c in line) / max(len(line), 1)
        if alpha_ratio < 0.4:
            continue
        if re.search(r"\d{2,4}[-/.]\d{1,2}[-/.]\d{2,4}", line):
            continue
        if re.match(r"^[\d\s.,]+$", line):
            continue
        vendor = line
        break
    if vendor is None and lines:
        vendor = lines[0]

    # --- Amount: bottom-up keyword scan (see _extract_amount) ---
    amount = _extract_amount(lines, text)

    # --- Date: keyword-context first, day-first parsing ---
    date = _extract_date(lines, text)

    # --- Currency: most frequent marker, INR default ---
    currency = detect_currency(text)

    return {
        "vendor": (vendor or "").strip() or None,
        "amount": amount,
        "date": date,
        "currency": currency,
    }
