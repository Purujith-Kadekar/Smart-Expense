"""
POST /api/register — create a new user account
POST /api/login    — authenticate and return a JWT

These are the only two API routes that do NOT require auth — every other
route is protected by the `require_auth` decorator.
"""

import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from services.auth import encode_token, hash_password, verify_password
from services.dynamo import create_user, get_user_by_email

auth_bp = Blueprint("auth", __name__)

# Minimum password length — enforced at registration. bcrypt itself has
# no minimum, but 8 chars is the standard floor for any modern app.
MIN_PASSWORD_LENGTH = 8


@auth_bp.post("/register")
def register():
    """Create a new user. Returns a JWT immediately so the frontend can
    log the user in without a separate /login call.

    Request:  { "email": "...", "password": "..." }
    Response: { "token": "...", "user_id": "...", "email": "..." }  (201)
    Errors:   400 invalid_email | password_too_short
              409 email_already_registered
    """
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    # Validate email — require something before AND after the `@`, with a
    # dot in the domain part. We don't send a verification email (hackathon
    # scope), but we do require a well-formed address.
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return jsonify({"error": "invalid_email"}), 400
    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({"error": "password_too_short",
                        "min_length": MIN_PASSWORD_LENGTH}), 400

    # Uniqueness check — scan the Users table for an existing email. In
    # production this would be a GSI Query, but scan is fine at hackathon
    # scale (see dynamo.get_user_by_email docstring).
    if get_user_by_email(email) is not None:
        return jsonify({"error": "email_already_registered"}), 409

    user_id = str(uuid.uuid4())
    user = {
        "user_id": user_id,
        "email": email,
        "password_hash": hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    create_user(user)

    token = encode_token(user_id)
    return jsonify({"token": token, "user_id": user_id, "email": email}), 201


@auth_bp.post("/login")
def login():
    """Authenticate an existing user. Returns a JWT on success.

    Request:  { "email": "...", "password": "..." }
    Response: { "token": "...", "user_id": "...", "email": "..." }
    Errors:   401 invalid_credentials (same message for wrong email AND
              wrong password — don't leak which one is wrong, that's an
              account-enumeration vector)
    """
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify({"error": "invalid_credentials"}), 401

    user = get_user_by_email(email)
    # Use the same error message for "no such email" and "wrong password"
    # so an attacker can't enumerate accounts by email.
    if user is None or not verify_password(password, user.get("password_hash", "")):
        return jsonify({"error": "invalid_credentials"}), 401

    token = encode_token(user["user_id"])
    return jsonify({"token": token, "user_id": user["user_id"], "email": user["email"]})
