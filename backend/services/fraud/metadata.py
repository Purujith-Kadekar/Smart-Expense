"""EXIF / metadata inspection.

Reads EXIF tags from the uploaded image and checks for:

  * Editing-software tags (`Software`, `ProcessingSoftware`, `CreatorTool`,
    `Producer`, `HistorySoftware` — these are written by Photoshop,
    GIMP, Canva, Lightroom, etc. when the file is saved through them).
  * Timestamp mismatches: EXIF `DateTimeOriginal` vs. the receipt
    date OCR extracted. A receipt dated "2026-03-18" but with EXIF
    capture time of "2025-01-01" is suspicious — either the EXIF is
    stale (re-used stock photo), or the receipt date was edited.
  * Stripped metadata on a JPEG: PNGs and screenshots legitimately
    have no EXIF, but a JPEG straight from a phone camera almost
    always has at least DateTimeOriginal + Make. A JPEG with zero
    EXIF is a weak signal that someone re-saved it (which strips
    EXIF in most editors' default save flow).
  * Dimension anomalies: a 200x200 "receipt" is suspiciously small;
    a 10,000x10,000 "receipt" is suspiciously large.

This module deliberately treats EXIF as a SOFT signal — the spec is
explicit: "Metadata should never be treated as definitive proof of
fraud". A single suspicious tag adds 15 to the score; a stripped JPEG
adds another 5; both together still leave the receipt in REVIEW (20
total), not FLAGGED.

Pillow's EXIF support is via `Image.getexif()` (returns an
`ExifTags` dict-like). If Pillow is unavailable or the file isn't an
image, the check returns a passing result with `details.skip_reason`
so the rest of the pipeline continues.

Why we don't use `exifread`: it's an extra dependency, and `Pillow`'s
`getexif()` covers all the fields we care about (Software, DateTime,
Make, Model, ExifImageWidth/Height, etc.). For the rare formats Pillow
doesn't parse (e.g. HEIC without the libheif plugin), the check
just records `exif_unavailable` and moves on.
"""

import re
from datetime import datetime, date as date_cls
from typing import Any, Dict, Optional

from .context import FraudContext
from .result import (
    CheckResult,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    fail,
    pass_,
    severity_rank,
)
from .safe_image import safe_open_image

# EXIF tag IDs we care about. Pillow's `getexif()` returns a dict keyed
# by integer tag ID. We use Pillow's `ExifTags.TAGS` lookup so we don't
# hardcode IDs (they vary slightly across formats).
try:
    from PIL import Image  # type: ignore
    from PIL.ExifTags import TAGS as _EXIF_TAGS  # type: ignore
    _PIL_OK = True
except ImportError:  # pragma: no cover
    _PIL_OK = False
    _EXIF_TAGS = {}

# Software tag values that indicate the file was processed through an
# image editor. Matched case-insensitively as a substring of the
# Software / ProcessingSoftware / CreatorTool field. The values mirror
# what the actual apps write — Photoshop writes "Adobe Photoshop X.Y",
# GIMP writes "GIMP X.Y", Canva writes "Canva", Lightroom writes
# "Adobe Lightroom X.Y", etc.
_EDITING_SOFTWARE_PATTERNS = [
    r"photoshop",
    r"adobe photoshop",
    r"gimp",
    r"canva",
    r"lightroom",
    r"capture one",
    r"affinity photo",
    r"pixelmator",
    r"snagit",
    r"paint\.net",
    r"pixlr",
    r"polarr",
    r"lightxeditor",
    r"picsart",
]
_EDITING_RE = re.compile("|".join(_EDITING_SOFTWARE_PATTERNS), re.IGNORECASE)

# EXIF DateTime is "YYYY:MM:DD HH:MM:SS" with colons, not slashes.
_EXIF_DATE_RE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})")

# Suspicious dimension ranges for a receipt.
# < 200px on either side is probably a thumbnail re-saved as the
# original. > 10,000px on either side is either a stitched image or a
# deliberately huge file to slow down OCR / fraud checks.
MIN_DIMENSION = 200
MAX_DIMENSION = 10_000


def _extract_exif(img) -> Dict[str, Any]:
    """Pull the EXIF tags we care about from a PIL Image.

    Returns an empty dict if the image has no EXIF (PNG, screenshot,
    re-saved JPEG). Returns `{"_error": "..."}` if `getexif()` itself
    raised — we treat that as "no EXIF available" rather than as a
    hard failure of the fraud check.

    The returned dict is keyed by EXIF tag NAME (e.g. "Software",
    "DateTimeOriginal", "Make"). That's what the rest of the module
    checks against — tag IDs are stable but opaque to readers.
    """
    out: Dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception as exc:
        return {"_error": str(exc)}
    if not exif:
        return out
    # `_EXIF_TAGS` is PIL's `ExifTags.TAGS` dict, keyed by tag ID (int)
    # with tag NAME (str) values. We want to look up tag-by-id → name,
    # so we use `_EXIF_TAGS` directly (no inversion). The previous
    # version here was buggy — it inverted the dict, then tried to look
    # up by int ID against a dict keyed by str NAME, which returned
    # None and fell through to `str(tag_id)` — so every EXIF tag
    # appeared in the output as a number rather than its name, and
    # the `exif.get("Software")` lookups below never matched anything.
    tag_id_to_name = _EXIF_TAGS if _EXIF_TAGS else {}
    for tag_id, value in exif.items():
        name = tag_id_to_name.get(tag_id) or str(tag_id)
        # Skip large binary data (thumbnail, ICC profile) — just note
        # that they exist.
        if isinstance(value, (bytes,)) and len(value) > 256:
            out[name] = f"<binary {len(value)} bytes>"
        else:
            try:
                out[name] = str(value)
            except Exception:
                out[name] = "<unprintable>"
    return out


def _parse_exif_date(s: str) -> Optional[date_cls]:
    """Parse EXIF DateTimeOriginal / DateTime strings.

    Format: "YYYY:MM:DD HH:MM:SS" or "YYYY:MM:DD HH:MM" or just
    "YYYY:MM:DD". Returns None if parsing fails.
    """
    if not s or not isinstance(s, str):
        return None
    m = _EXIF_DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def check_metadata(ctx: FraudContext) -> CheckResult:
    """Inspect EXIF metadata for tampering signals.

    The check is a SOFT signal — even when it fires, it contributes at
    most 30 to the fraud score (editing software 15 + timestamp
    mismatch 15), so a single suspicious tag alone won't push a
    receipt past REVIEW.
    """
    if not ctx.has_image:
        return pass_("metadata_anomaly", {"skip_reason": "no_image"})

    img, reason = safe_open_image(ctx.image_path)
    if img is None:
        # File itself unreadable — that's a different (heavier) check
        # handled by the image_unreadable signal. Don't double-report.
        return pass_("metadata_anomaly", {"skip_reason": reason})

    details: Dict[str, Any] = {}
    software_signals: list = []
    timestamp_mismatch = False
    stripped_jpeg = False
    dimension_anomaly = False
    fail_reasons = []
    weight_keys = []
    severities = []

    try:
        try:
            exif = _extract_exif(img)
        except Exception:
            exif = {}
        details["exif_keys"] = sorted(exif.keys()) if exif else []

        # ─── Software / editor tag check ────────────────────────
        software_fields = [
            exif.get("Software"),
            exif.get("ProcessingSoftware"),
            exif.get("CreatorTool"),
            exif.get("Producer"),
            exif.get("HistorySoftware"),
        ]
        for sf in software_fields:
            if not sf or not isinstance(sf, str):
                continue
            if _EDITING_RE.search(sf):
                software_signals.append(sf)
                weight_keys.append("metadata_editing_software")
                severities.append(SEVERITY_MEDIUM)
                fail_reasons.append(
                    f"Image metadata indicates editing software was used: {sf}"
                )
                break  # one software hit is enough

        # ─── DateTimeOriginal vs. receipt date ──────────────────
        exif_dt = _parse_exif_date(
            str(exif.get("DateTimeOriginal") or exif.get("DateTime") or "")
        )
        details["exif_capture_date"] = exif_dt.isoformat() if exif_dt else None
        if exif_dt and ctx.receipt_date:
            # Allow up to 7 days of skew: a receipt dated Monday could
            # be photographed any day that week (legitimate). Beyond
            # that, the EXIF date doesn't match the receipt's stated
            # date — possible re-use of an old photo, or a fabricated
            # receipt date.
            skew_days = abs((exif_dt - ctx.receipt_date).days)
            details["exif_date_skew_days"] = skew_days
            if skew_days > 7:
                timestamp_mismatch = True
                weight_keys.append("metadata_timestamp_mismatch")
                severities.append(SEVERITY_MEDIUM)
                fail_reasons.append(
                    f"Image capture date {exif_dt.isoformat()} does not match "
                    f"receipt date {ctx.receipt_date.isoformat()} "
                    f"({skew_days} days apart)"
                )

        # ─── Stripped-metadata-on-JPEG check ────────────────────
        fmt = (img.format or "").upper()
        details["image_format"] = fmt
        if fmt == "JPEG" and not exif:
            # PNG and WebP legitimately have no EXIF. But a JPEG straight
            # from a phone camera has at least DateTimeOriginal + Make.
            # No EXIF on a JPEG → re-saved through an editor that strips
            # metadata by default (e.g. Photoshop's "Save for Web").
            stripped_jpeg = True
            weight_keys.append("metadata_stripped_jpeg")
            severities.append(SEVERITY_LOW)
            fail_reasons.append(
                "JPEG has no EXIF metadata — may have been re-saved through an editor"
            )

        # ─── Dimension anomaly ─────────────────────────────────
        try:
            w, h = img.size
            details["dimensions"] = [w, h]
            if w < MIN_DIMENSION or h < MIN_DIMENSION:
                dimension_anomaly = True
                weight_keys.append("metadata_dimension_anomaly")
                severities.append(SEVERITY_MEDIUM)
                fail_reasons.append(
                    f"Suspiciously small image ({w}x{h}) — may be a thumbnail or low-quality scan"
                )
            elif w > MAX_DIMENSION or h > MAX_DIMENSION:
                dimension_anomaly = True
                weight_keys.append("metadata_dimension_anomaly")
                severities.append(SEVERITY_MEDIUM)
                fail_reasons.append(
                    f"Suspiciously large image ({w}x{h}) — may be a stitched or deliberately oversized image"
                )
        except Exception:
            pass

    finally:
        try:
            img.close()
        except Exception:
            pass

    if weight_keys:
        # Pick the strongest signal for the result; the others remain
        # in `details` for review. Pipeline sums scores across checks,
        # not across multiple signals within one check, so we report
        # only one — the worst. Use `severity_rank` to compare —
        # lexicographic comparison of severity strings would treat
        # "critical" < "high" as True, which is wrong.
        idx = max(range(len(severities)), key=lambda i: severity_rank(severities[i]))
        return fail(
            name="metadata_anomaly",
            weight_key=weight_keys[idx],
            severity=severities[idx],
            reason=fail_reasons[idx],
            details={
                **details,
                "all_signals": {
                    "editing_software": software_signals or None,
                    "timestamp_mismatch": timestamp_mismatch,
                    "stripped_jpeg": stripped_jpeg,
                    "dimension_anomaly": dimension_anomaly,
                },
            },
        )

    return pass_("metadata_anomaly", details)
