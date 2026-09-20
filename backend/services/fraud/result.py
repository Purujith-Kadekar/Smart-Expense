"""Dataclasses and scoring thresholds for the fraud pipeline.

This module deliberately holds NO logic — it's the contract between
the checkers (which produce CheckResults) and the pipeline (which
combines them into a FraudResult). Keeping the contract in one place
means a new checker just imports these classes and doesn't need to
know how its results get combined.

Scoring design
--------------
Each `CheckResult` carries a `score` (int 0-100, weight contributed
to the final fraud_score) and a `severity` (`info`, `low`, `medium`,
`high`, `critical`). The pipeline sums scores across all checks,
caps the sum at 100, and maps to a `FraudLevel`:

    0-24   VALID    no significant issues, accept
   25-59   REVIEW   suspicious, queue for human review
   60-100  FLAGGED  strong evidence of fraud, do not auto-approve

Multiple HIGH signals push the score into FLAGGED even if no single
check is conclusive — this is the "multiple suspicious signals → very
high risk" rule from the spec.

Constants
---------
`WEIGHTS` is the single source of truth for how much each check
contributes. Tuning fraud scoring is a single-file edit, not a
sweep across modules.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# Severity → numeric band. The pipeline uses these to decide whether a
# single critical signal is enough to force FLAGGED regardless of the
# summed score (it is).
# ──────────────────────────────────────────────────────────────────────
SEVERITY_INFO = "info"
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"

_SEVERITY_RANK = {
    SEVERITY_INFO: 0,
    SEVERITY_LOW: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_HIGH: 3,
    SEVERITY_CRITICAL: 4,
}


# ──────────────────────────────────────────────────────────────────────
# Per-check weights. Add new signals here, not scattered across modules.
# ──────────────────────────────────────────────────────────────────────
WEIGHTS = {
    # Duplicate detection — strongest signal
    "duplicate_exact_hash":        60,   # same bytes
    "duplicate_phash_strong":      45,   # Hamming ≤ 5
    "duplicate_phash_weak":        25,   # Hamming 6-12
    "duplicate_content_fp":        35,   # merchant+date+amount+invoice reused

    # Metadata
    "metadata_editing_software":   15,   # Photoshop/GIMP/Canva tag
    "metadata_stripped_jpeg":      5,    # EXIF missing on a JPEG (common alone)
    "metadata_timestamp_mismatch": 15,   # EXIF time conflicts with receipt date
    "metadata_dimension_anomaly":  10,   # suspiciously small/large

    # ELA
    "ela_anomaly_moderate":        20,   # elevated regional variance
    "ela_anomaly_high":            35,   # strong tampering evidence

    # Math
    "math_inconsistency_high":     35,   # >1% drift or >₹1 absolute
    "math_inconsistency_low":      5,    # rounding only (≤₹1, ≤0.5%)

    # Logic
    "logic_future_date":           15,
    "logic_invalid_date":          25,
    "logic_non_positive_total":    30,
    "logic_reused_invoice_number": 40,
    "logic_gstin_invalid":         10,
    "logic_tax_mismatch":          20,

    # Defensive — file itself can't be trusted
    "image_unreadable":            30,
    "image_oversized":             20,
    "image_corrupt":               35,
}


# ──────────────────────────────────────────────────────────────────────
# Severity bands → a score this check contributes when it fires.
# Multiple signals that all map to the same weight are fine: pipeline
# sums them, so two MEDIUM ELA anomalies contribute 2 * ela_anomaly_moderate.
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Outcome of one fraud-detection check.

    Attributes:
        name: stable identifier of the check (e.g. "duplicate", "ela",
            "math_validation"). Used as the key in `FraudResult.checks`.
        passed: True if the check found no issue. False if it found
            evidence of fraud.
        weight_key: key into `WEIGHTS` — the score to contribute when
            `passed` is False. If None, the check contributes 0 even
            when failing (used for purely informational checks).
        severity: one of SEVERITY_* — used to force FLAGGED on a
            single critical signal.
        reason: human-readable explanation of what was detected. Empty
            string when `passed` is True. Each failed check's reason
            becomes an entry in `FraudResult.reasons`.
        details: free-form dict for diagnostic data (Hamming distance,
            expected vs. actual total, EXIF tags found, etc.). Stored
            alongside the result so reviewers can debug without
            re-running the pipeline.
    """
    name: str
    passed: bool
    weight_key: Optional[str] = None
    severity: str = SEVERITY_INFO
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> int:
        """Score contributed to the final fraud_score when this check fails."""
        if self.passed or not self.weight_key:
            return 0
        return WEIGHTS.get(self.weight_key, 0)


# ──────────────────────────────────────────────────────────────────────
# Final aggregate result. Stored on the expense record as
# `fraud_result` (a JSON blob) plus the scalar `fraud_score` and
# `fraud_level` for quick filtering.
# ──────────────────────────────────────────────────────────────────────
LEVEL_VALID = "VALID"
LEVEL_REVIEW = "REVIEW"
LEVEL_FLAGGED = "FLAGGED"


def severity_rank(severity: str) -> int:
    """Numeric rank for a severity string. Higher = more severe.

    Used by checkers that pick the worst of multiple signals (e.g.
    the duplicate checker has 3 signals and picks the most severe).
    Comparing severity strings directly with `<` is a bug — Python
    compares them lexicographically ("critical" < "high" is True
    alphabetically, but CRITICAL is *more* severe than HIGH).
    """
    return _SEVERITY_RANK.get(severity, 0)


def score_to_level(score: int, has_critical: bool = False) -> str:
    """Map a 0-100 score to a fraud level.

    `has_critical` lets a single CRITICAL-severity signal (e.g. exact
    file-hash duplicate) force FLAGGED even if other checks passed and
    the summed score is below 60. This is the rule that catches the
    case where one signal is conclusive but the rest are noise.
    """
    if has_critical or score >= 60:
        return LEVEL_FLAGGED
    if score >= 25:
        return LEVEL_REVIEW
    return LEVEL_VALID


@dataclass
class FraudResult:
    """Aggregate outcome of the whole fraud pipeline.

    Stored on the expense record. The serializable form (via
    `to_dict()`) goes to:
      - the `fraud_result` field in DynamoDB (full detail for review)
      - the `GET /api/expenses/<id>/fraud` endpoint response
    """
    status: str = LEVEL_VALID
    fraud_score: int = 0
    risk_level: str = LEVEL_VALID
    checks: Dict[str, CheckResult] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        """Record a check's outcome. Idempotent — calling twice with
        the same name overwrites the prior result (which is what we
        want if the pipeline is re-run on the same receipt)."""
        self.checks[result.name] = result
        if not result.passed and result.reason:
            # Avoid duplicate reason strings if the same check fires twice.
            if result.reason not in self.reasons:
                self.reasons.append(result.reason)

    def finalize(self) -> None:
        """Compute the aggregate score + level from accumulated checks.

        Must be called once at the end of the pipeline before reading
        `fraud_score` / `risk_level` / `status`.
        """
        total = 0
        has_critical = False
        for r in self.checks.values():
            total += r.score
            if not r.passed and _SEVERITY_RANK.get(r.severity, 0) >= _SEVERITY_RANK[SEVERITY_CRITICAL]:
                has_critical = True
        # Cap at 100 — once you're at 100 you're definitely FLAGGED,
        # no point pretending a 173-score receipt is worse than a 100.
        self.fraud_score = min(100, total)
        self.risk_level = score_to_level(self.fraud_score, has_critical)
        # `status` mirrors `risk_level` — the spec uses both names.
        self.status = self.risk_level

    def to_dict(self) -> Dict[str, Any]:
        """Serializable form for DynamoDB storage + API responses."""
        return {
            "status": self.status,
            "fraud_score": self.fraud_score,
            "risk_level": self.risk_level,
            "checks": {
                name: {
                    "passed": r.passed,
                    "severity": r.severity,
                    "reason": r.reason,
                    "details": r.details,
                }
                for name, r in self.checks.items()
            },
            "reasons": list(self.reasons),
        }


# ──────────────────────────────────────────────────────────────────────
# Helper constructors — checkers use these so they don't have to spell
# out every field each time.
# ──────────────────────────────────────────────────────────────────────
def pass_(name: str, details: Optional[Dict[str, Any]] = None) -> CheckResult:
    """A check that found no issue."""
    return CheckResult(
        name=name,
        passed=True,
        severity=SEVERITY_INFO,
        reason="",
        details=details or {},
    )


def fail(name: str, weight_key: str, severity: str, reason: str,
         details: Optional[Dict[str, Any]] = None) -> CheckResult:
    """A check that detected an issue."""
    return CheckResult(
        name=name,
        passed=False,
        weight_key=weight_key,
        severity=severity,
        reason=reason,
        details=details or {},
    )
