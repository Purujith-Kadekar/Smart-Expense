"""Defensive PIL.Image loader for untrusted receipt uploads.

Receipts come from end-user browsers via S3. They can be:

  * Corrupt or truncated (interrupted upload)
  * Maliciously crafted decompression bombs (a 30MB JPEG that
    decompresses to 95,000 x 95,000 pixels and OOMs the worker)
  * Of an unsupported format (a PDF or a GIF pretending to be a JPEG)
  * Huge but legitimate (a 12 MP phone photo)

This module wraps `PIL.Image.open` with three safety nets:

  1. **`MAX_DECODE_PIXELS` cap** — checked AFTER opening by reading
     `image.size`. We deliberately do NOT set `Image.MAX_IMAGE_PIXELS`
     globally (the previous version did) — that's a process-wide
     state change that would also cap the OCR step (`pytesseract`
     and `easyocr` both call `PIL.Image.open`), causing legitimate
     large receipts (e.g. a 30MP scan) to fail OCR with
     `DecompressionBombError` even though they're fine. The cap
     here is scoped to the fraud-pipeline's own image access only.
  2. **`MAX_FILE_BYTES` cap** — checked before opening. A 30MB
     "receipt" is almost certainly malicious; reject at the file-stat
     layer before PIL even reads a header.
  3. **`.verify()` before `.open()` for a real load** — PIL's `verify()`
     checks the file's checksum / structure without decoding pixel
     data. We `verify()` then re-open for actual pixel access.

The function returns either a usable `PIL.Image` (mode may be converted
to RGB for downstream ELA work) or `None` if the file is unusable, with
the reason captured in the second return value. Callers MUST handle the
`None` case — typically by recording a "image_unreadable" check result
and continuing the pipeline (so a corrupt file doesn't crash the
ingestion, just flags it).
"""

import os
from typing import Optional, Tuple

# 24 megapixel equivalent — a 6000x4000 phone photo is 24MP. Anything
# larger than this on a *receipt* is suspicious. Real receipts are
# typically <2MP.
MAX_DECODE_PIXELS = 24_000_000

# 8 MB — a JPEG of a phone-captured receipt is typically 200KB-1.5MB.
# Anything over 8MB is either a lossless PNG of a huge document (still
# suspicious for a "receipt") or a bomb.
MAX_FILE_BYTES = 8 * 1024 * 1024  # 8 MiB

try:
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover — Pillow is in requirements
    Image = None  # type: ignore
    _PIL_AVAILABLE = False


# Reasons returned to callers when the loader bails out. Keeping them
# as named constants means callers can switch on them without typos.
REASON_OK = "ok"
REASON_PIL_MISSING = "pillow_not_installed"
REASON_FILE_MISSING = "file_not_found"
REASON_FILE_TOO_LARGE = "file_too_large"
REASON_BOMB = "decompression_bomb"
REASON_CORRUPT = "corrupt_or_unsupported"
REASON_TRUNCATED = "truncated"


def safe_open_image(path: str) -> Tuple[Optional[object], str]:
    """Open `path` as a PIL Image, defensively.

    Returns `(image, reason)` where `image` is a usable RGB-converted
    `PIL.Image.Image` on success or `None` on failure, and `reason` is
    one of the `REASON_*` constants above.

    On success, the returned image is in RGB mode (alpha is flattened,
    palette is expanded, grayscale is broadcast) because downstream ELA
    needs three identical channels to compute per-region compression
    differences.

    The caller does NOT need to close the image — PIL owns the file
    handle and closes it on `__del__`. If you want to be explicit, wrap
    in a `try/finally` and call `image.close()`.
    """
    if not _PIL_AVAILABLE:
        return None, REASON_PIL_MISSING

    if not path or not os.path.exists(path):
        return None, REASON_FILE_MISSING

    try:
        size = os.path.getsize(path)
    except OSError:
        return None, REASON_FILE_MISSING

    if size > MAX_FILE_BYTES:
        return None, REASON_FILE_TOO_LARGE

    # Step 1: verify() — cheap structural check that does NOT decode
    # pixel data. Catches truncated files and bad headers before we
    # allocate a pixel buffer.
    try:
        with Image.open(path) as probe:
            probe.verify()
    except Image.DecompressionBombError:
        return None, REASON_BOMB
    except Exception:
        # verify() raised — file is corrupt, truncated, or not an
        # image at all (PDF, random bytes, etc). Don't even try to
        # load it.
        return None, REASON_CORRUPT

    # Step 2: actually load pixels. Re-open because verify() leaves the
    # file pointer at EOF and the probe is no longer usable for pixel
    # access.
    try:
        img = Image.open(path)
        # `load()` actually decodes. If the file is truncated, PIL
        # raises here even if `verify()` passed (verify only checks
        # headers; load() walks the actual scan data).
        img.load()
    except Image.DecompressionBombError:
        return None, REASON_BOMB
    except (OSError, ValueError):
        return None, REASON_TRUNCATED
    except Exception:
        # Defensive catch-all — any other PIL failure means we can't
        # trust this file. Treat as corrupt.
        return None, REASON_CORRUPT

    # Step 3: dimension cap (scoped — does NOT modify global PIL state).
    # We check this AFTER load() because some image formats (e.g.
    # animated PNGs) don't report the true decoded size until pixels
    # are loaded.
    try:
        w, h = img.size
        if w * h > MAX_DECODE_PIXELS:
            try:
                img.close()
            except Exception:
                pass
            return None, REASON_BOMB
    except Exception:
        pass

    # Convert to RGB for downstream ELA / EXIF consistency. We do NOT
    # resize here — callers (phash, ELA) resize as needed for their own
    # algorithms.
    if img.mode != "RGB":
        try:
            img = img.convert("RGB")
        except Exception:
            return None, REASON_CORRUPT

    return img, REASON_OK


def image_dimensions(path: str) -> Optional[Tuple[int, int]]:
    """Return `(width, height)` of the image at `path`, or None if
    the file can't be opened.

    Uses the safe loader — same bomb/corrupt protections apply. Used
    by the metadata inspector for the dimensions check."""
    img, _ = safe_open_image(path)
    if img is None:
        return None
    try:
        return img.size
    finally:
        try:
            img.close()
        except Exception:
            pass
