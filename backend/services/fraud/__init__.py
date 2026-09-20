"""Outlay fraud-detection system.

Public API:
    run_fraud_pipeline(...)  — the orchestrator. Import this and call
                              it from the ingestion pipeline.

The checkers (duplicate, metadata, ela, math_check, logic_check) are
deliberately NOT re-exported here — callers should depend on the
pipeline, not the individual detectors. This means we can swap a
checker out (e.g. replace pHash with a perceptual-net model) without
changing any call site.
"""

from .context import FraudContext
from .pipeline import run_fraud_pipeline
from .result import (
    CheckResult,
    FraudResult,
    LEVEL_FLAGGED,
    LEVEL_REVIEW,
    LEVEL_VALID,
)

__all__ = [
    "run_fraud_pipeline",
    "FraudContext",
    "FraudResult",
    "CheckResult",
    "LEVEL_FLAGGED",
    "LEVEL_REVIEW",
    "LEVEL_VALID",
]
