"""FraudContext — the shared input bundle passed to every checker.

The pipeline builds ONE context object per receipt and passes it to
each checker. Checkers read only the fields they need; missing fields
default to None / empty so a checker can decide to skip cleanly when
its inputs aren't available (e.g. EXIF check skips when there's no
image path, math check skips when OCR didn't extract line items).

This decoupling is what makes the checkers independently testable
and individually replaceable — the spec requires "modular so
individual detection methods can be replaced or improved later".
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class FraudContext:
    """Everything a fraud checker might need to know about a receipt.

    Attributes:
        user_id: who is uploading
        s3_key: where the file lives in S3 (also the idempotency key)
        image_path: local tmp path the receipt was downloaded to.
            None when the pipeline is running in mock mode (where
            `download_image_from_s3` is stubbed to return a path that
            doesn't actually exist) or when the S3 download failed.
        ocr_text: raw text returned by OCR. Empty string in mock mode
            or when OCR failed.
        parsed: the dict from `parse_ocr_text(ocr_text)` — vendor,
            amount, date, currency. Values may be None / 0.
        category: the receipt category (college/mess/event/other),
            from the S3 key path.
        existing_items: the user's previously-ingested receipts, as a
            list of dicts. Used by the duplicate checker to compare
            against prior uploads. Empty list is fine (first upload).
        existing_fingerprints: list of (file_hash, phash, user_id,
            expense_id, s3_key, content_fp) tuples from the
            `ReceiptFingerprints` table — used for cross-receipt
            duplicate detection. None when the fingerprints table
            isn't available (the duplicate check degrades to
            content-level only).
        uploaded_at: when the upload was initiated (UTC). Used for the
            future-date check (a receipt dated after this is future).
        receipt_date: parsed `date` from OCR, as a `date` object if
            parseable, else None.
        line_items: optional structured line items if the OCR parser
            exposed them. None when OCR didn't extract line items —
            the math check then degrades to "single total only".
        invoice_number: invoice/receipt number extracted by OCR. None
            if not present.
        gstin: GSTIN extracted by OCR. None if not present.
    """
    user_id: str
    s3_key: str
    image_path: Optional[str] = None
    ocr_text: str = ""
    parsed: Dict[str, Any] = field(default_factory=dict)
    category: str = "other"
    existing_items: List[Dict[str, Any]] = field(default_factory=list)
    existing_fingerprints: List[Dict[str, Any]] = field(default_factory=list)
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    receipt_date: Optional[date] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    invoice_number: Optional[str] = None
    gstin: Optional[str] = None

    # Convenience: the original (pre-FX) amount the OCR parser found.
    @property
    def original_amount(self) -> float:
        try:
            return float(self.parsed.get("amount") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def currency(self) -> str:
        return (self.parsed.get("currency") or "INR").upper()

    @property
    def vendor(self) -> str:
        return (self.parsed.get("vendor") or "Unknown").strip()

    @property
    def has_image(self) -> bool:
        """True iff a readable image file is available for hashing/EXIF/ELA."""
        if not self.image_path:
            return False
        import os
        return os.path.exists(self.image_path)
