"""Fraud-detection pipeline orchestrator.

The pipeline runs the modular checkers in the order mandated by the
spec:

  1. Compute file hashes (SHA-256 + pHash) BEFORE OCR — so exact and
     perceptual duplicate detection can short-circuit an attacker
     re-uploading the same file, without paying the OCR cost.
  2. Run duplicate check (uses the hashes + content fingerprint).
  3. Inspect EXIF metadata.
  4. Run ELA / image-forensics.
  5. Mathematical validation (uses OCR-extracted data).
  6. Logical validation (uses OCR-extracted data + prior receipts).
  7. Combine all signals into a final FraudResult.

Each checker is wrapped in a try/except so a single broken checker
does not crash the ingestion. A crashed checker contributes a
"check_failed" entry to the result with severity LOW (we don't want
a bug in one detector to silently downgrade a fraudulent receipt —
but we also don't want to claim "VALID" when we couldn't actually
run a check). The pipeline also logs every failure via `print()`
(consistent with the rest of the codebase which uses `print` rather
than `logging` — keeping the existing pattern).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .context import FraudContext
from .duplicate import check_duplicate
from .ela import check_ela
from .hashing import compute_hashes
from .logic_check import check_logic
from .math_check import check_math
from .metadata import check_metadata
from .result import (
    CheckResult,
    FraudResult,
    SEVERITY_LOW,
    SEVERITY_INFO,
    fail,
    pass_,
)
from .safe_image import safe_open_image


def _safe_run(name: str, fn, ctx: FraudContext, *args, **kwargs) -> CheckResult:
    """Run one checker, catching any unexpected exception.

    A checker that raises returns a soft-failure CheckResult with
    severity LOW so the receipt doesn't appear "VALID" just because a
    detector crashed. The exception is logged via `print()` for
    visibility.
    """
    try:
        result = fn(ctx, *args, **kwargs)
        if not isinstance(result, CheckResult):
            # A checker returned something weird — treat as soft-failure.
            return fail(
                name=name,
                weight_key=None,
                severity=SEVERITY_LOW,
                reason=f"Checker {name} returned non-CheckResult: {type(result).__name__}",
                details={"raw": str(result)[:500]},
            )
        return result
    except Exception as exc:
        # Log so the operator can see *which* checker crashed and why.
        import traceback
        print(f"[fraud] Checker '{name}' raised: {exc}")
        traceback.print_exc()
        return fail(
            name=name,
            weight_key=None,
            severity=SEVERITY_LOW,
            reason=f"Fraud check '{name}' could not be completed (internal error)",
            details={"exception": str(exc)[:300]},
        )


def run_fraud_pipeline(
    *,
    user_id: str,
    s3_key: str,
    image_path: Optional[str],
    ocr_text: str,
    parsed: Dict[str, Any],
    category: str = "other",
    existing_items: List[Dict[str, Any]] = None,
    existing_fingerprints: List[Dict[str, Any]] = None,
    uploaded_at: Optional[datetime] = None,
    invoice_number: Optional[str] = None,
    line_items: Optional[List[Dict[str, Any]]] = None,
    gstin: Optional[str] = None,
) -> Tuple[FraudResult, Optional[str], Optional[int]]:
    """Run the full fraud pipeline on a receipt.

    Returns `(result, file_hash, phash)`:
      * `result` — FraudResult with all check outcomes + final score/level.
      * `file_hash` — SHA-256 of the file, or None. The Lambda stores
        this on the expense record so future duplicate checks can find
        it without re-hashing.
      * `phash` — 64-bit perceptual hash, or None. Same use.

    All arguments are keyword-only so the caller can't accidentally
    swap positional args.

    The pipeline is idempotent: re-running on the same `s3_key`
    produces the same result (modulo non-deterministic EXIF timestamps
    in the `details` dict). The Lambda uses this property to safely
    re-run when an s3_key is re-triggered.
    """
    # ─── 1. Build the context ─────────────────────────────────────
    # Parse the receipt date into a `date` object — needed by the
    # future-date check and the EXIF-timestamp-mismatch check.
    receipt_date = None
    raw_date = parsed.get("date") or ""
    if raw_date:
        try:
            receipt_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            receipt_date = None

    ctx = FraudContext(
        user_id=user_id,
        s3_key=s3_key,
        image_path=image_path,
        ocr_text=ocr_text,
        parsed=parsed,
        category=category,
        existing_items=existing_items or [],
        existing_fingerprints=existing_fingerprints or [],
        uploaded_at=uploaded_at or datetime.now(timezone.utc),
        receipt_date=receipt_date,
        line_items=line_items,
        invoice_number=invoice_number or parsed.get("invoice_number"),
        gstin=gstin or parsed.get("gstin"),
    )

    result = FraudResult()

    # ─── 2. Image-availability probe ─────────────────────────────
    # Used to decide whether the image-based checks (hashing, EXIF,
    # ELA) can actually run, or whether we should record a defensive
    # "image_unreadable" signal.
    image_status = "ok"
    if not ctx.has_image:
        image_status = "no_image"
    else:
        img, reason = safe_open_image(ctx.image_path)
        if img is None:
            image_status = reason  # 'corrupt_or_unsupported', 'file_too_large', etc.
        else:
            try:
                img.close()
            except Exception:
                pass

    # If the image itself is unreadable, that's a HIGH-severity signal
    # — either the file is genuinely corrupt (which is a soft failure
    # we should still flag), or it's a deliberately malformed file the
    # attacker used to try to crash the pipeline.
    if image_status not in ("ok", "no_image"):
        weight_key = {
            "corrupt_or_unsupported": "image_corrupt",
            "file_too_large": "image_oversized",
            "decompression_bomb": "image_oversized",
            "truncated": "image_corrupt",
            "decompression_bomb_error": "image_oversized",
        }.get(image_status, "image_corrupt")
        result.add(fail(
            name="image_unreadable",
            weight_key=weight_key,
            severity=SEVERITY_LOW if weight_key == "image_oversized" else "high",
            reason=f"Image file could not be inspected ({image_status}) — fraud checks that depend on pixel data were skipped",
            details={"image_status": image_status},
        ))

    # ─── 3. Compute hashes (before OCR-driven checks) ────────────
    file_hash = None
    phash = None
    if image_status == "ok":
        try:
            file_hash, phash = compute_hashes(ctx.image_path)
        except Exception as exc:
            print(f"[fraud] Hashing failed for {ctx.image_path}: {exc}")
            result.add(fail(
                name="hashing",
                weight_key=None,
                severity=SEVERITY_LOW,
                reason=f"File hashing failed: {exc}",
                details={"exception": str(exc)[:300]},
            ))

    # ─── 4. Duplicate detection ──────────────────────────────────
    dup_result = _safe_run("duplicate", check_duplicate, ctx,
                           file_hash=file_hash, phash=phash)
    result.add(dup_result)

    # ─── 5. EXIF / metadata inspection ──────────────────────────
    meta_result = _safe_run("metadata_anomaly", check_metadata, ctx)
    result.add(meta_result)

    # ─── 6. ELA / image forensics ───────────────────────────────
    ela_result = _safe_run("ela_anomaly", check_ela, ctx)
    result.add(ela_result)

    # ─── 7. Mathematical validation ─────────────────────────────
    math_result = _safe_run("math_validation", check_math, ctx)
    result.add(math_result)

    # ─── 8. Logical validation ──────────────────────────────────
    logic_result = _safe_run("logic_validation", check_logic, ctx)
    result.add(logic_result)

    # ─── 9. Combine ────────────────────────────────────────────
    result.finalize()

    # ─── 10. Log every failure for audit ─────────────────────────
    # The spec requires "Add clear backend logging for every validation
    # failure." We log via print() — consistent with the rest of the
    # codebase which uses print() rather than Python's logging module.
    for r in result.checks.values():
        if not r.passed:
            print(
                f"[fraud] CHECK FAILED: {r.name} | "
                f"severity={r.severity} | "
                f"weight={r.weight_key} | "
                f"reason={r.reason}"
            )

    return result, file_hash, phash
