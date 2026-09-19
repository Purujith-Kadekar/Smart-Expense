"""
Authentication helpers — bcrypt password hashing, JWT encode/decode, and
a `require_auth` decorator that protects Flask routes.

Token format: HS256-signed JWT with `sub` (user_id), `iat`, `exp` claims.
Default expiry: 24 hours. Override via JWT_EXPIRY_HOURS env var.

JWT_SECRET must be set in production (use `python -c "import secrets;
print(secrets.token_hex(32))"` to generate one). For local dev / mock
mode, a fixed default is used so the app runs zero-config.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import jsonify, request

# Read config at import time. In production these MUST come from env:
#   JWT_SECRET=<random 64-char hex string>
# For local dev, a fixed default lets `python app.py` work zero-config.
# An EMPTY JWT_SECRET (the .env.example placeholder) is treated as unset —
# PyJWT would otherwise happily sign every token with an empty HMAC key,
# which is trivially forgeable.
JWT_SECRET = (os.environ.get("JWT_SECRET") or "").strip() or \
    "dev-secret-change-in-production-do-not-use-in-prod"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Bcrypt-hash a plaintext password. Returns a str (not bytes) so it
    can be stored in DynamoDB as a String attribute.

    bcrypt has a 72-byte password limit. To handle arbitrarily long
    passwords without losing entropy, we pre-hash with SHA-256 before
    bcrypt. This is a well-known pattern (see pyca/bcrypt#12) and does
    NOT weaken security — bcrypt still does the slow KDF on the SHA-256
    digest.
    """
    if not password:
        raise ValueError("password must not be empty")
    sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return bcrypt.hashpw(sha256.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash. Returns
    False if either input is empty/malformed rather than raising — the
    caller (login route) treats all False results the same way."""
    if not password or not password_hash:
        return False
    sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
    try:
        return bcrypt.checkpw(sha256.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash — treat as verification failure, don't crash.
        return False


# ---------------------------------------------------------------------------
# JWT encode / decode
# ---------------------------------------------------------------------------

def encode_token(user_id: str) -> str:
    """Issue a signed JWT for the given user_id. Expiry is JWT_EXPIRY_HOURS
    from now. Returns a str (PyJWT 2.x returns str, not bytes)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Verify and decode a JWT. Raises jwt.ExpiredSignatureError if
    expired, jwt.InvalidTokenError for any other validation failure.
    The caller (require_auth) catches both and returns 401."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# require_auth decorator
# ---------------------------------------------------------------------------

def require_auth(fn):
    """Decorator: protects a Flask route with JWT auth.

    Reads the `Authorization: Bearer <token>` header, verifies the token,
    and attaches `request.user_id` (the JWT `sub` claim) before calling
    the wrapped function.

    Returns 401 with a JSON error body if:
      - The Authorization header is missing or not `Bearer ...`
      - The token is expired
      - The token is invalid (bad signature, malformed, etc.)

    Usage:
        @expenses_bp.get("/expenses")
        @require_auth
        def get_expenses():
            user_id = request.user_id  # available thanks to the decorator
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing_or_invalid_auth_header"}), 401
        token = auth_header[len("Bearer "):].strip()
        if not token:
            return jsonify({"error": "missing_token"}), 401
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "token_expired"}), 401
        except jwt.InvalidTokenError:
            # Covers bad signature, malformed, wrong algorithm, etc.
            return jsonify({"error": "invalid_token"}), 401
        # Attach the user_id so the wrapped route can use it without
        # re-parsing the token.
        request.user_id = payload["sub"]
        return fn(*args, **kwargs)
    return wrapper
