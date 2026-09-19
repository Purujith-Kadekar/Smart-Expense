"""
Smart Campus Expense & Invoice Verifier — Flask backend

Entrypoint: registers CORS, wires up the route blueprints, and starts the
dev server. Everything runs locally against LocalStack — there is no cloud
deployment target for this project.

API contract (every route is under /api and protected by @require_auth
except /register, /login, and /health):

    POST /api/register            — create account, returns JWT
    POST /api/login               — authenticate, returns JWT

    POST /api/upload-url          — presigned S3 PUT URL (category required)
    GET  /api/expenses            — list caller's receipts (per-user)
    GET  /api/expenses/<id>       — single receipt (ownership-checked)
    POST /api/expenses/email      — email selected receipts as a bill via SES

    GET  /api/budget?month=YYYY-MM — budget_limit, income, total_spent, savings
    POST /api/budget               — upsert monthly budget (limit + income)

    GET  /health                   — liveness probe (no auth)
"""

import os

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

from routes.upload import upload_bp
from routes.expenses import expenses_bp
from routes.budget import budget_bp
from routes.auth import auth_bp
from services.mock_aws import is_mock_mode

# Load variables from backend/.env when present (local dev). On Elastic
# Beanstalk these come from environment properties instead, so missing
# .env is not an error.
load_dotenv()

app = Flask(__name__)

# Determine which AWS backend to use:
#   - MOCK_AWS=1 → in-memory stubs (for `python app.py` dev without Docker)
#   - AWS_ENDPOINT_URL set → real boto3 calls against LocalStack (docker-compose)
#   - Neither → real AWS (production / `aws configure` already run)
# is_mock_mode() auto-detects: if no AWS creds are configured locally and
# MOCK_AWS isn't explicitly set, it defaults to mock so `python app.py`
# works zero-config. In docker-compose, MOCK_AWS is unset and
# AWS_ENDPOINT_URL points at LocalStack, so real boto3 calls are used.
if is_mock_mode():
    print("[backend] MOCK_AWS active — using in-memory stubs (no AWS credentials found)")
    print("[backend] For the full stack: docker-compose up (uses LocalStack)")
else:
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "real AWS")
    print(f"[backend] Connecting to {endpoint}")

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
