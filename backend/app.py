"""
Outlay — Flask backend

Entrypoint: registers CORS, wires up the route blueprints, and starts the
dev server. Everything runs locally against LocalStack — there is no cloud
deployment target for this project.

API contract (every route is under /api and protected by @require_auth
except /register, /login, and /health):

    POST /api/register            — create account, returns JWT
    POST /api/login               — authenticate, returns JWT

    POST /api/upload-url          — presigned S3 PUT URL (category required)
    GET  /api/expenses            — list caller's receipts (per-user, INR)
    GET  /api/expenses/<id>       — single receipt (ownership-checked)
    POST /api/expenses/email      — email selected receipts as a bill via SES

    GET  /api/budget?month=YYYY-MM — budget_limit, income, total_spent, savings
    POST /api/budget               — upsert monthly budget (limit + income)

    GET  /api/system/storage      — which DynamoDB is in use + reachability
                                     (no auth) — answers "why isn't data saving?"
    GET  /health                   — liveness probe (no auth)

All monetary amounts in API responses are INR (₹). Receipts detected in a
foreign currency are converted to INR automatically at upload time using
the live rate fetched by the ingestion pipeline — see lambda/fx.py. There
is deliberately NO exchange-rates API or UI: conversion is invisible.
"""

import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from routes.upload import upload_bp
from routes.expenses import expenses_bp
from routes.budget import budget_bp
from routes.auth import auth_bp
from services.mock_aws import mock_item_counts, storage_mode_info

# Load variables from backend/.env when present (local dev). On Elastic
# Beanstalk these come from environment properties instead, so missing
# .env is not an error.
load_dotenv()

app = Flask(__name__)

# Storage-failure surfacing: any UNHANDLED botocore error (LocalStack down,
# missing table, credential problem) becomes a clean JSON 503 instead of
# an HTML 500 — so the frontend can finally answer "why isn't this
# saving?". Import is guarded because a mock-only dev box may not have
# boto3 installed (services/mock_aws.py imports it lazily for the same
# reason).
try:
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover — mock-only dev without boto3
    BotoCoreError = ClientError = None

if BotoCoreError is not None:

    @app.errorhandler(BotoCoreError)
    @app.errorhandler(ClientError)
    def _storage_backend_error(err):
        """Translate botocore failures into a JSON 503 with the real cause.

        ClientError examples this catches: ResourceNotFoundException (the
        tables were never created — run localstack/init.py),
        UnrecognizedClientException / AccessDeniedException (bad AWS
        credentials). BotoCoreError examples: EndpointConnectionError
        (LocalStack is not running / wrong AWS_ENDPOINT_URL).
        """
        app.logger.exception("Storage backend error")
        return jsonify({
            "error": "storage_unavailable",
            "detail": str(err),
            "hint": "The backend cannot reach its storage (DynamoDB/S3). "
                    "Check GET /api/system/storage — common causes: "
                    "LocalStack not running, tables never created "
                    "(localstack/init.py), or a wrong AWS_ENDPOINT_URL.",
        }), 503

# Determine which AWS backend to use:
#   - MOCK_AWS=1 → in-memory stubs (for `python app.py` dev without Docker)
#   - AWS_ENDPOINT_URL set → real boto3 calls against LocalStack (docker-compose)
#   - Neither → real AWS (production / `aws configure` already run)
# is_mock_mode() auto-detects: if no AWS creds are configured locally and
# MOCK_AWS isn't explicitly set, it defaults to mock so `python app.py`
# works zero-config. In docker-compose, MOCK_AWS is unset and
# AWS_ENDPOINT_URL points at LocalStack, so real boto3 calls are used.
_storage = storage_mode_info()
if _storage["mode"] == "mock":
    if _storage["persistent"]:
        print(f"[backend] MOCK_AWS active — in-memory stubs, persisted to {_storage['persist_file']}")
    else:
        print("[backend] MOCK_AWS active — in-memory stubs (no AWS credentials found)")
        print("[backend] WARNING: in-memory storage RESETS on every restart — accounts,")
        print("[backend] budgets and receipts will vanish. Set MOCK_PERSIST_FILE in")
        print("[backend] backend/.env to keep data (see README 'Storage & persistence').")
    print("[backend] For the full stack: docker-compose up (uses LocalStack)")
elif _storage["mode"] == "aws":
    print("[backend] Storage: real Amazon DynamoDB/S3 (durable) — AWS_ENDPOINT_URL unset")
else:
    print(f"[backend] Storage: {_storage['endpoint']} (AWS-compatible local endpoint)")
    if not _storage["persistent"]:
        print("[backend] NOTE: LocalStack Community keeps state in memory only —")
        print("[backend] restarting the stack wipes accounts/budgets/receipts.")

# CORS — hardened for cross-domain dev/deploy. The React dev server runs on
# a different origin (http://localhost:5173) than Flask (http://localhost:5000),
# so every API call from the browser is cross-origin and needs proper CORS
# headers. Vite auto-increments the port if 5173 is taken (5174, 5175, ...),
# so we always allow any http://localhost:* origin via regex, in addition to
# any origins explicitly listed in ALLOWED_ORIGINS.
#
# Configure production origins via the ALLOWED_ORIGINS env var (comma-separated):
#   ALLOWED_ORIGINS=https://expense-dashboard.example.edu
# When unset, only localhost origins are allowed (fine for dev).
import re as _re
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
_allowed_origins = []
if _allowed_origins_raw:
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

# Always allow localhost on any port — Vite picks 5173 by default but
# auto-increments to 5174, 5175, etc. if the port is taken. Hardcoding
# 5173 breaks the moment a second Vite instance starts. Regex patterns
# are natively supported by flask-cors and more reliable than a callable.
_allowed_origins.extend([
    _re.compile(r"^http://localhost(:\d+)?$"),
    _re.compile(r"^http://127\.0\.0\.1(:\d+)?$"),
])


# All CORS options go inside `resources` — passing some at top level and some
# inside resources causes flask-cors to merge them in a way that lets unknown
# origins through the allowlist. Keeping everything in one place fixes that.
#
# The pattern `r"/*"` covers every route, including `/health` and 404s.
# This is deliberate: when someone hits a non-existent URL (e.g. a typo
# like `/expenses` instead of `/api/expenses`), flask-cors still adds the
# ACAO header so the browser can read the actual 404 response body
# instead of showing a misleading "CORS error".
CORS(
    app,
    resources={
        r"/*": {
            "origins": _allowed_origins,
            # Explicit method allowlist — axios fetch with
            # `Content-Type: application/json` triggers a preflight OPTIONS
            # request, and the preflight response must echo back every
            # method/headers the actual request will use.
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            # `Content-Type` is needed for JSON bodies. `Authorization` is
            # preemptively allowlisted in case we add token auth later (it's
            # free and avoids a second CORS debugging session).
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            # Expose error/response headers to the browser so axios
            # interceptors can read them on failure.
            "expose_headers": ["Content-Type", "X-Request-ID"],
            # Credentials off — we're not using cookies, and `*` origin is
            # incompatible with `credentials: true` anyway. Flip to True if
            # you add session cookies.
            "supports_credentials": False,
            # Cache the preflight response for 1 hour so the browser doesn't
            # re-OPTIONS every single API call (matters for the dashboard's
            # 15-second polling).
            "max_age": 3600,
        }
    },
)

# Blueprint registration — one blueprint per logical resource group.
app.register_blueprint(upload_bp, url_prefix="/api")
app.register_blueprint(expenses_bp, url_prefix="/api")
app.register_blueprint(budget_bp, url_prefix="/api")
app.register_blueprint(auth_bp, url_prefix="/api")


@app.get("/health")
def health():
    """Liveness probe used by the docker-compose healthcheck."""
    return {"status": "ok", "service": "outlay-backend"}


@app.get("/api/system/storage")
def storage_diagnostics():
    """Which storage backend is active, and is it actually reachable?

    This is the "why isn't my data saving?" endpoint. No auth (like
    /health) so it can be checked from a browser or curl even when login
    itself is broken (e.g. the Users table is missing).

    Response: {
      "storage": { mode, endpoint, persistent, persist_file },
      "tables": { expenses|users|budgets: { table, reachable, status,
                                             item_count, engine, error? } },
      "s3":     { bucket, reachable, note? , error? },
      "checked_at": <iso8601>
    }

    In non-mock modes the checks use throwaway clients with 2-3s timeouts
    and no retries, so a dead endpoint answers "reachable: false" quickly
    instead of hanging the diagnostics call for a minute.
    """
    from datetime import datetime, timezone

    info = storage_mode_info()
    table_names = {
        "expenses": os.environ.get("TABLE_NAME", "ExpenseRecords"),
        "users": os.environ.get("USERS_TABLE_NAME", "Users"),
        "budgets": os.environ.get("BUDGETS_TABLE_NAME", "Budgets"),
    }
    bucket = os.environ.get("S3_BUCKET", "receipts-bucket")
    tables = {"expenses": None, "users": None, "budgets": None}
    s3 = {"bucket": bucket}

    if info["mode"] == "mock":
        counts = mock_item_counts()
        for label, name in table_names.items():
            tables[label] = {
                "table": name,
                "reachable": True,
                "status": "ACTIVE",
                "item_count": counts.get(name, 0),
                "engine": "in-memory"
                + (" + file" if info["persist_file"] else ""),
            }
        s3.update({"reachable": True, "note": "mock — objects are not stored"})
    else:
        import boto3
        from botocore.client import Config

        fast = Config(connect_timeout=2, read_timeout=3,
                      retries={"max_attempts": 1})
        client_kwargs = {
            "region_name": os.environ.get("AWS_REGION", "us-east-1"),
            "config": fast,
        }
        if info["endpoint"]:
            client_kwargs["endpoint_url"] = info["endpoint"]
        try:
            dynamo = boto3.client("dynamodb", **client_kwargs)
            for label, name in table_names.items():
                try:
                    described = dynamo.describe_table(TableName=name)
                    meta = described.get("Table", {})
                    tables[label] = {
                        "table": name,
                        "reachable": True,
                        "status": meta.get("TableStatus", "UNKNOWN"),
                        "item_count": meta.get("ItemCount", 0),
                        "engine": info["endpoint"] or "real AWS",
                    }
                except Exception as exc:  # ClientError per table
                    tables[label] = {
                        "table": name,
                        "reachable": False,
                        "engine": info["endpoint"] or "real AWS",
                        "error": str(exc),
                    }
        except Exception as exc:  # boto3 import / client construction
            for label, name in table_names.items():
                tables[label] = {
                    "table": name,
                    "reachable": False,
                    "error": str(exc),
                }
        try:
            s3_client = boto3.client("s3", **client_kwargs)
            s3_client.head_bucket(Bucket=bucket)
            s3["reachable"] = True
        except Exception as exc:
            s3["reachable"] = False
            s3["error"] = str(exc)

    return jsonify({
        "storage": info,
        "tables": tables,
        "s3": s3,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })


@app.errorhandler(404)
def not_found(err):
    """Custom 404 handler that emits JSON (not the default HTML 404 page)
    AND propagates CORS headers.

    Without this, hitting a non-existent route (e.g. a typo like `/expenses`
    instead of `/api/expenses`) returns Flask's default HTML 404 — which
    flask-cors may or may not have wrapped with ACAO depending on the
    resource pattern. The result in the browser is a misleading "CORS
    error" that's actually a 404. Returning JSON here + letting flask-cors
    handle the headers makes the real error visible to axios.
    """
    from flask import jsonify, request

    return jsonify({
        "error": "not_found",
        "path": request.path,
        "hint": "All API routes live under /api/* — did you forget the /api prefix?",
    }), 404


@app.errorhandler(405)
def method_not_allowed(err):
    """Same treatment for 405 Method Not Allowed — return JSON with CORS
    headers so axios can read the actual error instead of a CORS wall."""
    from flask import jsonify, request

    return jsonify({
        "error": "method_not_allowed",
        "method": request.method,
        "path": request.path,
    }), 405


if __name__ == "__main__":
    # Bind all interfaces so the container port mapping works. The image
    # runs gunicorn instead; this path is for `python app.py` on the host.
    port = int(os.environ.get("PORT", "5000"))
    # Debug mode is OFF by default — Flask's interactive debugger exposes
    # arbitrary code execution on the server if it's reachable from the
    # internet, which is a real exposure now that the app guards passwords
    # and a JWT secret. Set FLASK_DEBUG=1 in .env for local dev to get
    # auto-reload + better error pages; never set it in production.
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes", "on"}
    if debug:
        print("[backend] FLASK_DEBUG=1 — debug mode ON (auto-reload + interactive debugger)")
        print("[backend] NEVER use this in production — it allows remote code execution.")
    app.run(host="0.0.0.0", port=port, debug=debug)
