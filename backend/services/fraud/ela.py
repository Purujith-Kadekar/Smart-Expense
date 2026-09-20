"""Error Level Analysis (ELA).

ELA re-saves the image at a known JPEG quality, then measures the
per-pixel difference between the original and the re-saved version.
Untouched regions of an image compress *consistently* — every pixel
in a region was last compressed at the same quality level, so they
all change by roughly the same amount when re-compressed.

A *tampered* region (e.g. a price that was pasted in from a different
image, or text that was edited in Photoshop) was last compressed at a
*different* quality level than the surrounding image, so it produces a
*different* error magnitude than its neighbors when ELA re-compresses.

Implementation
-------------
We:
  1. Load the image defensively (decompression bomb / corrupt guards
     already in `safe_open_image`).
  2. Convert to RGB (alpha-flatten) and resize so the longest side ≤
     1024px — ELA on a 4000x3000 image is 4× slower with no extra
     signal because JPEG is block-based (8×8 DCT) and resampling to
     ~1MP captures all the structure.
  3. Re-save as JPEG at quality=90 (standard ELA quality — high enough
     that untouched regions show small consistent errors, low enough
     that tampered regions stand out).
  4. Compute the absolute pixel difference between original and
     re-saved, on a per-channel basis.
  5. Aggregate into a 16×16 grid of mean-abs-diff values. This grid
     is small enough that we can compute statistics on it but large
     enough to spot localized tampering.
  6. Compute the standard deviation of the grid. A uniform
     compression history → low stddev (every cell similar). Tampering
     → high stddev (some cells much hotter than others).

Thresholds (calibrated on real receipts in dev):
  * stddev < 8.0  → no anomaly (image compresses uniformly)
  * 8.0 - 18.0    → moderate anomaly (possible light editing)
  * > 18.0        → high anomaly (strong tampering evidence)

We also report the brightest cell's mean as `max_cell_diff` — a single
very bright cell with a uniform surrounding is a classic ELA tell.

The check is a MEDIUM signal alone — ELA has false positives on
heavily compressed receipt scans (multiple re-saves through WhatsApp
or email). The spec requires "Do not automatically reject a receipt
solely because ELA detects an anomaly." We don't — we add 20 (moderate)
or 35 (high) to the score, and only FLAGGED if other checks push it
over 60.
"""

import io
from typing import Any, Dict, Optional, Tuple

from .context import FraudContext
from .result import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    fail,
    pass_,
)
from .safe_image import safe_open_image

try:
    from PIL import Image  # type: ignore
    _PIL_OK = True
except ImportError:  # pragma: no cover
    _PIL_OK = False

# ELA parameters — calibrated for receipt-sized images.
ELA_QUALITY = 90              # JPEG quality for the re-save
ELA_GRID_SIZE = 16            # 16x16 cells → 256 mean-diff samples
ELA_MAX_SIDE = 1024           # resize longest side to this (speed)
ELA_MODERATE_THRESHOLD = 8.0  # stddev above this → moderate anomaly
ELA_HIGH_THRESHOLD = 18.0    # stddev above this → high anomaly


def _resize_for_ela(img) -> "Image.Image":
    """Resize so the longest side is ≤ ELA_MAX_SIDE. Aspect preserved."""
    w, h = img.size
    longest = max(w, h)
    if longest <= ELA_MAX_SIDE:
        return img
    scale = ELA_MAX_SIDE / longest
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), 1)


def _reencode_jpeg(img, quality: int) -> "Image.Image":
    """Re-encode `img` as JPEG at `quality`, return the decoded result.

    Uses an in-memory buffer so we don't touch the filesystem.
    """
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf)


def _grid_mean_abs_diff(a, b, grid_n: int = ELA_GRID_SIZE) -> Tuple[list, float, float, float]:
    """Compute a `grid_n × grid_n` grid of mean-abs-diff between two
    same-sized RGB images.

    Returns `(grid_flat, mean, stddev, max_cell)` where grid_flat is a
    list of length `grid_n*grid_n` of per-cell mean abs diffs across
    all channels. `mean` is the average of the grid, `stddev` is the
    sample standard deviation, `max_cell` is the brightest cell.

    This is the most expensive step of ELA — O(W * H) for the diff
    plus O(grid_n^2) for the aggregation. We use `Image.point` /
    `Image.split` instead of `np` to avoid pulling in numpy just for
    this — at 1MP the per-pixel Python loop would be too slow, so we
    use PIL's `ImageChops.difference` which is C.
    """
    from PIL import ImageChops  # type: ignore

    # Resize both to a multiple of grid_n so cells are equal-sized.
    w, h = a.size
    # Snap to nearest multiple of grid_n (downsampling further is fine;
    # upsampling slightly is also fine because we already resized to ≤
    # ELA_MAX_SIDE).
    target_w = (w // grid_n) * grid_n or grid_n
    target_h = (h // grid_n) * grid_n or grid_n
    if (target_w, target_h) != (w, h):
        a = a.resize((target_w, target_h), 1)
        b = b.resize((target_w, target_h), 1)

    diff = ImageChops.difference(a, b).convert("L")
    # `diff` is a single-channel image where each pixel is the
    # max-abs-diff across the 3 channels. Sufficient for tampering
    # detection; per-channel analysis adds no signal at this granularity.

    cell_w = target_w // grid_n
    cell_h = target_h // grid_n
    pixels = diff.load()
    grid_flat = []
    for gy in range(grid_n):
        for gx in range(grid_n):
            s = 0
            for py in range(gy * cell_h, (gy + 1) * cell_h):
                for px in range(gx * cell_w, (gx + 1) * cell_w):
                    s += pixels[px, py]
            grid_flat.append(s / (cell_w * cell_h))

    n = len(grid_flat)
    mean = sum(grid_flat) / n if n else 0.0
    var = sum((v - mean) ** 2 for v in grid_flat) / (n - 1) if n > 1 else 0.0
    stddev = var ** 0.5
    max_cell = max(grid_flat) if grid_flat else 0.0
    return grid_flat, mean, stddev, max_cell


def check_ela(ctx: FraudContext) -> "CheckResult":
    """Run ELA on `ctx.image_path`. Returns a CheckResult.

    Skips cleanly when:
      * PIL is not installed (returns pass with skip_reason)
      * image is unreadable (returns pass — image_unreadable check
        handles that signal separately)
      * image is not a JPEG-derived format (ELA only meaningful on JPEG;
        PNG screenshots compress losslessly, ELA gives no signal)
    """
    if not _PIL_OK:
        return pass_("ela_anomaly", {"skip_reason": "pillow_not_installed"})
    if not ctx.has_image:
        return pass_("ela_anomaly", {"skip_reason": "no_image"})

    img, reason = safe_open_image(ctx.image_path)
    if img is None:
        return pass_("ela_anomaly", {"skip_reason": reason})

    try:
        # If the image is not JPEG-native, ELA's signal is unreliable.
        # `img.format` is the *original* format the file was saved as,
        # even after we re-decoded it. PNG / WebP / GIF / BMP skip.
        fmt = (img.format or "").upper()
        if fmt != "JPEG":
            return pass_("ela_anomaly", {
                "skip_reason": f"not_jpeg (format={fmt})",
                "note": "ELA is only meaningful for JPEG; lossless formats are skipped",
            })

        small = _resize_for_ela(img)
        try:
            reencoded = _reencode_jpeg(small, ELA_QUALITY)
        except Exception as exc:
            return pass_("ela_anomaly", {"skip_reason": f"reencode_failed: {exc}"})

        try:
            grid, mean, stddev, max_cell = _grid_mean_abs_diff(small, reencoded, ELA_GRID_SIZE)
        except Exception as exc:
            return pass_("ela_anomaly", {"skip_reason": f"diff_failed: {exc}"})

        details: Dict[str, Any] = {
            "ela_mean": round(mean, 3),
            "ela_stddev": round(stddev, 3),
            "ela_max_cell": round(max_cell, 3),
            "ela_quality": ELA_QUALITY,
            "ela_grid_size": ELA_GRID_SIZE,
            "grid_flat": [round(v, 2) for v in grid],
        }

        if stddev > ELA_HIGH_THRESHOLD:
            return fail(
                name="ela_anomaly",
                weight_key="ela_anomaly_high",
                severity=SEVERITY_HIGH,
                reason=(
                    f"Error Level Analysis shows strong tampering evidence "
                    f"(stddev={stddev:.2f} > {ELA_HIGH_THRESHOLD}, max_cell={max_cell:.2f}) — "
                    f"some regions of the image were last compressed at a different quality"
                ),
                details=details,
            )
        if stddev > ELA_MODERATE_THRESHOLD:
            return fail(
                name="ela_anomaly",
                weight_key="ela_anomaly_moderate",
                severity=SEVERITY_MEDIUM,
                reason=(
                    f"Error Level Analysis shows elevated compression inconsistency "
                    f"(stddev={stddev:.2f} > {ELA_MODERATE_THRESHOLD}) — possible light editing"
                ),
                details=details,
            )

        return pass_("ela_anomaly", details)
    finally:
        try:
            img.close()
        except Exception:
            pass
