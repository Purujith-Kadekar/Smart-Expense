"""Duplicate-receipt detection.

Three independent signals:

  1. **Exact file-hash duplicate** — SHA-256 of the uploaded bytes
     matches a previously-stored fingerprint. Conclusive: the user is
     uploading the same file twice. Renaming doesn't help the attacker.

  2. **Perceptual-hash duplicate** — pHash (64-bit) Hamming distance
     ≤ 12 to a previously-stored fingerprint. The attacker re-saved,
     re-compressed, or stripped metadata, but the underlying image is
     the same. We split into two bands: ≤5 = "strong" (very likely
     the same image), 6-12 = "weak" (probably the same image with
     more aggressive edits). Both fire the duplicate check; the
     weak band contributes a smaller score.

  3. **Content-fingerprint duplicate** — same merchant + date + amount
     + invoice number as a previously-stored receipt. The attacker
     re-photographed the same physical receipt; the image bytes differ,
     the pHash differs (different angle, lighting, framing), but the
     receipt data is identical. This is the spec's "identical
     merchant + date + amount + invoice number combinations should
     receive a high duplicate/fraud score" rule.

All three are looked up against the `ReceiptFingerprints` table, which
is keyed by `file_hash` (SHA-256) and is scanned for pHash / content_fp
matches. At demo scale this is fine; at any real scale we'd add a GSI
on `phash_bucket` (the top 16 bits of the pHash — bucketed LSH) for
sublinear pHash lookup.

When the fingerprints table is unavailable (mock mode without persist
file, table-creation race, etc.), the check degrades gracefully —
the exact-hash and phash signals are skipped, only the content
fingerprint against the existing receipts (which the Lambda already
scanned) is evaluated.
"""

from typing import List, Optional

from .context import FraudContext
from .hashing import (
    compute_hashes,
    content_fingerprint,
    hamming_distance,
)
from .result import (
    CheckResult,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    fail,
    pass_,
    severity_rank,
)

# Hamming distance thresholds for 64-bit pHash. The imagehash library
# recommends ≤5 as "same image" and ≤10 as "probably same"; we extend
# the weak band to ≤12 to catch aggressive re-compression at low
# quality factors, at the cost of more false positives (which is why
# the weak band only contributes 25 score, not 45).
PHASH_STRONG_THRESHOLD = 5
PHASH_WEAK_THRESHOLD = 12


def _normalize_amount(a) -> float:
    """Defensive amount coercion — handles Decimal, int, float, str."""
    try:
        return round(float(a or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def check_duplicate(ctx: FraudContext, file_hash: Optional[str] = None,
                    phash: Optional[int] = None) -> CheckResult:
    """Run all three duplicate checks against `ctx.existing_fingerprints`.

    Returns the WORST outcome found — i.e. if any signal fires, the
    check fails with the most-severe reason. If no signal fires,
    returns a passing result with diagnostic details (the computed
    hash + phash, so reviewers can see what was compared).

    `file_hash` and `phash` are pre-computed by the pipeline and
    passed in. If they're None (e.g. image unreadable), only the
    content-fingerprint check runs.
    """
    reasons: List[str] = []
    details = {
        "file_hash": file_hash,
        "phash": phash,
        "matches": [],
    }
    worst_weight_key: Optional[str] = None
    worst_severity = SEVERITY_MEDIUM
    worst_severity_rank = severity_rank(SEVERITY_MEDIUM)
    has_match = False

    existing = ctx.existing_fingerprints or []

    # ─── 1. Exact file-hash duplicate ─────────────────────────────
    if file_hash:
        for fp in existing:
            if fp.get("file_hash") == file_hash:
                # Exclude the same s3_key (idempotent re-trigger).
                if fp.get("s3_key") == ctx.s3_key:
                    continue
                has_match = True
                details["matches"].append({
                    "type": "exact_hash",
                    "expense_id": fp.get("expense_id"),
                    "s3_key": fp.get("s3_key"),
                    "user_id": fp.get("user_id"),
                })
                # CRITICAL is the strongest signal; only set if not already
                # at CRITICAL (which can't happen here since this is the
                # first signal, but be defensive).
                if worst_severity_rank < severity_rank(SEVERITY_CRITICAL):
                    worst_weight_key = "duplicate_exact_hash"
                    worst_severity = SEVERITY_CRITICAL
                    worst_severity_rank = severity_rank(SEVERITY_CRITICAL)
                reasons.append(
                    "Receipt appears to have been submitted previously (exact file match)"
                )
                # No need to keep scanning — one exact match is conclusive.
                break

    # ─── 2. Perceptual-hash duplicate ─────────────────────────────
    if phash is not None:
        for fp in existing:
            other = fp.get("phash")
            if other is None:
                continue
            if fp.get("s3_key") == ctx.s3_key:
                continue
            try:
                other_int = int(other)
            except (TypeError, ValueError):
                continue
            dist = hamming_distance(phash, other_int)
            if dist <= PHASH_STRONG_THRESHOLD:
                has_match = True
                details["matches"].append({
                    "type": "phash_strong",
                    "distance": dist,
                    "expense_id": fp.get("expense_id"),
                    "s3_key": fp.get("s3_key"),
                })
                # Only override if pHash-strong is MORE severe than what we
                # already have. CRITICAL > HIGH, so an exact-hash hit
                # already recorded will NOT be downgraded to pHash-strong.
                if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                    worst_weight_key = "duplicate_phash_strong"
                    worst_severity = SEVERITY_HIGH
                    worst_severity_rank = severity_rank(SEVERITY_HIGH)
                reasons.append(
                    f"Visually identical to a previously submitted receipt "
                    f"(pHash Hamming distance {dist} ≤ {PHASH_STRONG_THRESHOLD})"
                )
                break
            elif dist <= PHASH_WEAK_THRESHOLD:
                has_match = True
                details["matches"].append({
                    "type": "phash_weak",
                    "distance": dist,
                    "expense_id": fp.get("expense_id"),
                    "s3_key": fp.get("s3_key"),
                })
                # Only override if we don't already have a stronger signal.
                if worst_severity_rank < severity_rank(SEVERITY_MEDIUM):
                    worst_weight_key = "duplicate_phash_weak"
                    worst_severity = SEVERITY_MEDIUM
                    worst_severity_rank = severity_rank(SEVERITY_MEDIUM)
                reasons.append(
                    f"Visually similar to a previously submitted receipt "
                    f"(pHash Hamming distance {dist} — likely edited/resaved)"
                )
                # Don't break — there may be a strong match further on.

    # ─── 3. Content-fingerprint duplicate ─────────────────────────
    new_cf = content_fingerprint(
        ctx.vendor,
        (ctx.parsed.get("date") or ""),
        ctx.original_amount,
        ctx.invoice_number,
    )
    details["content_fingerprint"] = new_cf
    seen_cf = set()

    # From existing_fingerprints (if the schema stored content_fp)
    for fp in existing:
        if fp.get("s3_key") == ctx.s3_key:
            continue
        prior = fp.get("content_fingerprint")
        if prior and prior == new_cf:
            has_match = True
            details["matches"].append({
                "type": "content_fingerprint",
                "expense_id": fp.get("expense_id"),
                "s3_key": fp.get("s3_key"),
            })
            if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                worst_weight_key = "duplicate_content_fp"
                worst_severity = SEVERITY_HIGH
                worst_severity_rank = severity_rank(SEVERITY_HIGH)
            reasons.append(
                "Same merchant + date + amount + invoice number as a previously submitted receipt"
            )
            break

    # From existing_items (the scan the Lambda already did) — covers
    # receipts ingested before the fingerprints table existed.
    for item in ctx.existing_items:
        if item.get("s3_key") == ctx.s3_key:
            continue
        if item.get("user_id") != ctx.user_id:
            continue
        prior_cf = content_fingerprint(
            item.get("vendor") or "",
            item.get("date") or "",
            _normalize_amount(item.get("original_amount", item.get("amount"))),
            item.get("invoice_number"),
        )
        # Skip duplicates within the prior-receipts set itself.
        if prior_cf in seen_cf:
            continue
        seen_cf.add(prior_cf)
        if prior_cf == new_cf:
            has_match = True
            details["matches"].append({
                "type": "content_fingerprint",
                "expense_id": item.get("expense_id"),
                "s3_key": item.get("s3_key"),
            })
            if worst_severity_rank < severity_rank(SEVERITY_HIGH):
                worst_weight_key = "duplicate_content_fp"
                worst_severity = SEVERITY_HIGH
                worst_severity_rank = severity_rank(SEVERITY_HIGH)
            reasons.append(
                "Same merchant + date + amount + invoice number as a previously submitted receipt"
            )
            break

    if has_match:
        # De-duplicate the reasons list (the same content-FP can fire
        # both branches above with the same message).
        seen = set()
        unique_reasons = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)
        return fail(
            name="duplicate",
            weight_key=worst_weight_key or "duplicate_phash_weak",
            severity=worst_severity,
            reason=unique_reasons[0] if unique_reasons else "Duplicate detected",
            details=details,
        )

    return pass_(name="duplicate", details=details)
