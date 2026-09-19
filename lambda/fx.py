"""
FX — automatic one-time conversion of receipts to INR (the base currency).

Design contract (read this before touching anything):
  * The app's base currency is INR. Every `amount` written to DynamoDB is
    the INR value. Receipts detected in a foreign currency are converted
    ONCE, at upload/ingest time, using the live rate at that moment. The
    rate is then frozen onto the record (`fx_rate`) and is NEVER re-applied
    — later exchange-rate movement does not rewrite history.
  * Conversion is fully automatic and invisible: the rate is fetched by the
    ingestion pipeline itself — there is no exchange-rates API, panel or
    widget anywhere in the app. The only rate a user ever sees is the
    frozen one stamped on their own receipts.

Rate source (no API key, free, no signup):
  https://open.er-api.com/v6/latest/INR
  Returns {"result":"success","base_code":"INR",
           "rates":{"USD":0.0121,...}, ...} — i.e. units of <ccy> per 1 INR.
  We invert each rate to get "INR per 1 unit of <ccy>", which is the
  multiplier the conversion needs: amount_inr = original_amount * rate.

Resilience:
  * 3-second timeout (default, FX_TIMEOUT env) — a slow rate API must not
    stall the ingest pipeline.
  * In-process cache (FX_CACHE_TTL, default 60s) — warm Lambda invocations
    and bursts of uploads don't re-fetch for every single receipt.
  * Static fallback table — if the API is unreachable (offline demo,
    flaky hackathon wifi), conversion still works and the record is
    stamped fx_source="fallback" so it's auditable.

Stdlib only (urllib, json, threading) — no new dependency in
lambda/requirements.txt, works identically in AWS Lambda and the Flask
backend (both import this same file; the backend mounts lambda/ on
sys.path already — see routes/upload.py and the Dockerfile PYTHONPATH).
"""

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone

BASE_CURRENCY = "INR"

# Where the live rates come from. Overridable via env so tests / air-gapped
# demos can point it at a local stub.
FX_API_URL = os.environ.get("FX_API_URL", "https://open.er-api.com/v6/latest/INR")

# How long a successful (or failed) fetch is remembered. 60s keeps a burst
# of uploads (and warm Lambda invocations) from re-fetching the API for
# every single receipt — the network fetch happens at most once a minute
# per worker.
FX_CACHE_TTL = float(os.environ.get("FX_CACHE_TTL", "60"))

# Network timeout for the rate fetch. Deliberately short: conversion is on
# the critical path of ingestion, so we prefer a stale/fallback rate over a
# slow upload.
FX_TIMEOUT = float(os.environ.get("FX_TIMEOUT", "3"))

# Static fallback: INR per 1 unit of each currency, approx mid-2026 values.
# ONLY used when the live API is unreachable. Records converted with these
# are stamped fx_source="fallback" so reviewers can tell.
FALLBACK_RATES_TO_INR = {
    "USD": 83.00,
    "EUR": 90.50,
    "GBP": 105.50,
    "JPY": 0.55,
    "AED": 22.60,
    "AUD": 54.50,
    "CAD": 61.00,
    "SGD": 62.00,
    "CHF": 94.00,
    "CNY": 11.40,
}

# ---------------------------------------------------------------------------
# Cache + fetch
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cache = {
    "fetched_at": 0.0,          # time.time() of the last fetch attempt
    "fetched_at_iso": None,     # wall-clock stamp returned to clients
    "rates": None,               # {CCY: INR-per-unit multiplier}
    "source": None,              # "live" | "fallback"
}

# Test hook — counts actual network fetch attempts.
fetch_count = 0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _fetch_live_rates():
    """Fetch live rates from the rate API.

    Returns {CCY: INR-per-unit-of-CCY multiplier} on success, or None on any
    failure (network, timeout, bad payload). Never raises — callers treat
    None as "use the fallback table".
    """
    global fetch_count
    fetch_count += 1
    try:
        req = urllib.request.Request(
            FX_API_URL,
            headers={"User-Agent": "outlay/1.0"},
        )
        with urllib.request.urlopen(req, timeout=FX_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        raw = payload.get("rates")
        if not isinstance(raw, dict) or not raw:
            return None
        # The API returns units of <ccy> per 1 INR — invert to get
        # INR per 1 unit of <ccy>. amount_inr = original * inverted_rate.
        out = {}
        for code, per_inr in raw.items():
            try:
                per_inr = float(per_inr)
            except (TypeError, ValueError):
                continue
            if per_inr > 0:
                out[str(code).upper()] = 1.0 / per_inr
        # Sanity gate: a real response carries 150+ currencies. A tiny or
        # empty dict means the payload wasn't what we expected.
        if len(out) < 5:
            return None
        return out
    except Exception as exc:
        print(f"[fx] live rate fetch failed ({FX_API_URL}): {exc}")
        return None


def _reset_cache():
    """Test hook — clear the cache so the next get_rates() re-fetches."""
    with _lock:
        _cache.update(fetched_at=0.0, fetched_at_iso=None, rates=None, source=None)


def get_rates(force=False):
    """Return (rates, source, fetched_at_iso).

    rates   — {CCY: INR per 1 unit of CCY} (a copy; safe to mutate)
    source  — "live" or "fallback"
    fetched_at_iso — ISO timestamp of the fetch (for display)

    Cached for FX_CACHE_TTL seconds. A failed fetch also counts as a
    cached attempt — otherwise every ingest during an outage would burn a
    3-second timeout against a dead network.
    """
    with _lock:
        now = time.time()
        fresh = (
            _cache["rates"] is not None
            and (now - _cache["fetched_at"]) < FX_CACHE_TTL
        )
        if fresh and not force:
            return dict(_cache["rates"]), _cache["source"], _cache["fetched_at_iso"]

        live = _fetch_live_rates()
        if live is not None:
            _cache.update(
                rates=live,
                source="live",
                fetched_at=now,
                fetched_at_iso=_now_iso(),
            )
        else:
            _cache.update(
                rates=dict(FALLBACK_RATES_TO_INR),
                source="fallback",
                fetched_at=now,
                fetched_at_iso=_now_iso(),
            )
        return dict(_cache["rates"]), _cache["source"], _cache["fetched_at_iso"]


# ---------------------------------------------------------------------------
# Conversion (the one-time, freeze-at-upload operation)
# ---------------------------------------------------------------------------

def rate_to_inr(currency):
    """Return (rate, source) for 1 unit of `currency` in INR.

    INR itself → (1.0, "native"). A currency missing from both the live
    response and the fallback table → (1.0, "assumed_inr") — we'd rather
    store the number as-is and flag it than drop the receipt.
    """
    code = (currency or BASE_CURRENCY).strip().upper()
    if code == BASE_CURRENCY:
        return 1.0, "native"

    rates, source, _ = get_rates()
    if code in rates:
        return float(rates[code]), source
    if code in FALLBACK_RATES_TO_INR:
        return FALLBACK_RATES_TO_INR[code], "fallback"
    return 1.0, "assumed_inr"


def convert_to_inr(amount, currency):
    """Convert `amount` of `currency` into INR using the current rate.

    Returns a dict with everything the ingest pipeline stores on the
    expense record:
        {
          "currency":       original ISO code ("USD"),
          "original_amount": 4.86                (as printed on the receipt),
          "amount_inr":     404.60               (frozen INR value),
          "rate":           83.25                (1 USD = 83.25 INR),
          "source":         "live" | "fallback" | "native" | "assumed_inr",
          "fetched_at":     ISO timestamp of the rate used,
        }

    INR inputs pass through untouched (rate 1.0, source "native") — no
    network call, no rounding surprises for the 99% Indian-receipt case.
    """
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        amount = 0.0

    code = (currency or BASE_CURRENCY).strip().upper()

    if code == BASE_CURRENCY:
        return {
            "currency": code,
            "original_amount": round(amount, 2),
            "amount_inr": round(amount, 2),
            "rate": 1.0,
            "source": "native",
            "fetched_at": _now_iso(),
        }

    rates, source, fetched_at = get_rates()
    rate = rates.get(code)
    if rate is None:
        rate = FALLBACK_RATES_TO_INR.get(code)
    if rate is None:
        # Unknown ISO code (OCR hallucinated one?) — store as-is, flagged.
        return {
            "currency": code,
            "original_amount": round(amount, 2),
            "amount_inr": round(amount, 2),
            "rate": 1.0,
            "source": "assumed_inr",
            "fetched_at": fetched_at or _now_iso(),
        }

    rate = float(rate)
    return {
        "currency": code,
        "original_amount": round(amount, 2),
        "amount_inr": round(amount * rate, 2),
        "rate": round(rate, 6),
        "source": source,
        "fetched_at": fetched_at,
    }
