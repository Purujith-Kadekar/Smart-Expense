"""File hashing — cryptographic (SHA-256) and perceptual (pHash).

Two hashes serve different purposes:

  * **SHA-256 of the raw bytes** — exact-duplicate detection. Two
    uploads with the same SHA-256 are byte-for-byte identical, full
    stop. Renaming, re-uploading, or copying the file does not change
    it. The downside: ANY edit (re-saving, recompression, even a single
    byte of metadata change) produces a different SHA-256. So an
    attacker who resaves the JPEG to strip EXIF before re-uploading
    bypasses this hash.

  * **pHash (perceptual hash)** — content-level duplicate detection.
    Reduces the image to an 8x8 grayscale DCT, then thresholds the
    DCT coefficients into a 64-bit hash. Robust to: resize up to ~2x /
    down to ~50%, JPEG recompression at quality ≥ 50, mild cropping
    (≤10% of frame), color correction, EXIF stripping, and metadata
    changes. NOT robust to: heavy crop, text overlays, rotation > ~5°.

The two hashes are stored side-by-side in the `ReceiptFingerprints`
table. The duplicate checker compares new uploads against both:
SHA-256 → exact match (conclusive); pHash → Hamming distance, with
two thresholds (≤5 = strong, 6-12 = weak).

Implementation notes
-------------------
We use a hand-rolled DCT because the `imagehash` package isn't in the
existing requirements and pulling it in just for a 64-bit hash is
overkill. The DCT is the standard one used by phash.org / the
`imagehash` library — we compute it on a 32x32 grayscale image, keep
the top-left 8x8 (low-frequency) block, threshold at the median, and
pack into a 64-bit int.

Why 32x32 input → 8x8 DCT: the standard pHash recipe downsizes to
32x32 (so the DCT has enough frequency resolution), then takes the
top-left 8x8 block of the resulting 32x32 DCT (low frequencies are
where the structural content lives; high frequencies are noise that
changes under recompression). Median threshold (rather than mean)
gives a roughly 50/50 bit distribution which maximizes entropy.
"""

import hashlib
from typing import Optional, Tuple

from .safe_image import safe_open_image


def compute_sha256(path: str) -> Optional[str]:
    """SHA-256 of the file at `path`, hex-encoded. None if unreadable.

    We stream the file in 1 MiB chunks so a 4 MB receipt doesn't load
    entirely into memory — OOM safety on a 2-worker gunicorn.
    """
    if not path:
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


# ──────────────────────────────────────────────────────────────────────
# Minimal DCT-II implementation for pHash. We avoid numpy to dodge a
# new heavy dependency (the existing stack already pulls in torch via
# EasyOCR — but we shouldn't *rely* on torch being importable in the
# fraud module, because the spec says OCR_ENGINE can be 'tesseract'
# which has no torch). A pure-Python 8x8 DCT on a 32x32 input is ~1ms.
# ──────────────────────────────────────────────────────────────────────
import math

# Precompute the 8x8 DCT basis matrix at import time. The element at
# (i, j) is:
#     cos((2*j + 1) * i * pi / (2*N))
# where N=8 here. We then need the input to be downsampled to 32x32,
# DCT'd to 32x32, and the top-left 8x8 block taken.
#
# A more efficient approach computes a 32-point DCT directly, but the
# naive "compute 32x32 DCT then slice" recipe is simpler and still
# ~10ms. We precompute the 32x32 matrix once.

_DCT_N = 32
_DCT_MATRIX = None


def _dct_basis(n: int):
    """Pre-compute the n×n DCT-II basis matrix."""
    basis = []
    for i in range(n):
        row = []
        for j in range(n):
            # Standard DCT-II normalization: factor = sqrt(1/N) when
            # i=0 (DC term), sqrt(2/N) otherwise. For pHash we don't
            # actually need the normalization (we threshold by median,
            # which absorbs any constant scale), so we skip it.
            row.append(math.cos((2 * j + 1) * i * math.pi / (2 * n)))
        basis.append(row)
    return basis


def _ensure_dct_matrix():
    global _DCT_MATRIX
    if _DCT_MATRIX is None:
        _DCT_MATRIX = _dct_basis(_DCT_N)
    return _DCT_MATRIX


def _to_grayscale_pixels(img, size: int = _DCT_N):
    """Resize `img` to `size`×`size` grayscale, return as flat list of
    floats in [0, 255]. PIL's `.resize(..., Image.LANCZOS)` is high
    quality; for pHash we want *consistent* downsampling (the
    comparison is across two images processed identically), not the
    fastest possible."""
    small = img.convert("L").resize((size, size), 1)  # 1 = LANCZOS
    return list(small.getdata())


def _dct_2d(pixels: list, n: int = _DCT_N) -> list:
    """Compute the 2D DCT-II of an n×n image given as a flat list of
    pixels in row-major order. Returns a flat list of n*n coefficients.

    Brute force: M @ X @ M^T where M is the n×n basis. O(n^3) but n=32
    so it's ~32k mults — well under 10ms in CPython.
    """
    basis = _ensure_dct_matrix()
    # Step 1: row-wise DCT — multiply each row by basis matrix.
    # row_dct[i][k] = sum_j basis[k][j] * pixels[i*n + j]
    row_dct = [0.0] * (n * n)
    for i in range(n):
        row_base = i * n
        for k in range(n):
            bk = basis[k]
            s = 0.0
            for j in range(n):
                s += bk[j] * pixels[row_base + j]
            row_dct[row_base + k] = s

    # Step 2: column-wise DCT on the result.
    # out[i*n + k] = sum_j basis[k][j] * row_dct[j*n + i]
    out = [0.0] * (n * n)
    for i in range(n):
        for k in range(n):
            bk = basis[k]
            s = 0.0
            for j in range(n):
                s += bk[j] * row_dct[j * n + i]
            out[i * n + k] = s
    return out


def _top_left_block(coeffs: list, block_n: int = 8, full_n: int = _DCT_N) -> list:
    """Take the top-left `block_n`×`block_n` of the full DCT, as a flat
    list of length `block_n*block_n`. This is the standard pHash
    recipe — low frequencies live in the top-left of the DCT output.
    """
    out = []
    for i in range(block_n):
        for j in range(block_n):
            out.append(coeffs[i * full_n + j])
    return out


def _median(values: list) -> float:
    """Median of a list. Used as the pHash threshold — half the bits
    will be 1, half 0, maximizing hash entropy."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def compute_phash(path: str) -> Optional[int]:
    """64-bit perceptual hash of the image at `path`.

    Returns None if the image can't be opened. The returned int has
    exactly 64 bits — bit `i` is 1 iff `top_left_block[i] > median`.

    The int is stored as-is in DynamoDB (Number type). To compare two
    hashes, XOR them and count set bits (Hamming distance).
    """
    img, _ = safe_open_image(path)
    if img is None:
        return None
    try:
        pixels = _to_grayscale_pixels(img, _DCT_N)
    finally:
        try:
            img.close()
        except Exception:
            pass

    coeffs = _dct_2d(pixels, _DCT_N)
    block = _top_left_block(coeffs, 8, _DCT_N)
    med = _median(block)

    bits = 0
    for i, c in enumerate(block):
        if c > med:
            bits |= (1 << i)
    return bits


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two 64-bit pHashes."""
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def compute_hashes(path: str) -> Tuple[Optional[str], Optional[int]]:
    """Convenience: return both SHA-256 and pHash for the same file.

    Used by the duplicate checker — we compute both in one call so the
    file only gets opened once for pHash (SHA-256 reads bytes directly
    and doesn't need PIL, so it's basically free).
    """
    sha = compute_sha256(path)
    ph = compute_phash(path)
    return sha, ph


def content_fingerprint(vendor: str, date_str: str, amount: float,
                        invoice_number: Optional[str] = None) -> str:
    """A non-image fingerprint of the receipt's *content*.

    Concatenates normalized vendor + date + amount + invoice_number,
    SHA-256's the result. Two receipts with the same fingerprint are
    content-level duplicates — same merchant, same date, same total,
    (optionally) same invoice number. This catches the case where an
    attacker re-photographs the same physical receipt (different image
    bytes, different pHash, but identical receipt data).

    Amount is rounded to 2dp and zero-padded so 12.5 and 12.50 produce
    the same fingerprint. Vendor is lowercased + stripped of
    whitespace+punctuation. Invoice number is optional — when None
    it's omitted (and the fingerprint is weaker, but still useful
    against the receipts that DO share the invoice number).
    """
    import re as _re
    v = _re.sub(r"[^a-z0-9]+", "", (vendor or "").lower().strip())
    d = (date_str or "").strip()
    a = f"{float(amount or 0):.2f}"
    inv = (invoice_number or "").strip().lower()
    raw = f"{v}|{d}|{a}|{inv}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
