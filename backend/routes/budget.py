"""
POST /api/budget           — upsert monthly budget (limit + income) for the
                             authenticated user.
GET  /api/budget?month=... — returns { month, budget_limit, income,
                             total_spent, savings } for the user+month.

The `month` parameter is "YYYY-MM". Defaults to the current UTC month when
omitted on GET. POST requires `month` in the body.

savings = income - total_spent   (can be negative if the user overspent)

Protected by `@require_auth`.
"""

import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from services.auth import require_auth
from services.dynamo import get_budget, put_budget, list_expenses_for_month

budget_bp = Blueprint("budget", __name__)

# YYYY-MM — strict format, rejects "2026-1" (must be zero-padded) and
# "2026-13" (month out of range). Pre-compiled so we don't recompile on
# every request.
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _current_month():
    """Return the current UTC month as 'YYYY-MM'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _validate_month(month):
    """Return True if `month` matches YYYY-MM with a valid month 01-12."""
    return bool(month and _MONTH_RE.match(month))


@budget_bp.post("/budget")
@require_auth
def set_budget():
    """Upsert the authenticated user's budget for a month.

    Request:  { "month": "2026-09", "budget_limit": 20000, "income": 50000 }
    Response: { "user_id", "month", "budget_limit", "income", "updated_at" }
    Errors:   400 invalid_month | invalid_budget_limit | invalid_income
    """
    body = request.get_json(silent=True) or {}
    month = (body.get("month") or "").strip()
    budget_limit = body.get("budget_limit")
    income = body.get("income")

    if not _validate_month(month):
        return jsonify({
            "error": "invalid_month",
            "hint": "month must be 'YYYY-MM' (e.g. '2026-09'), zero-padded.",
        }), 400

    # budget_limit and income must be non-negative numbers. We allow them
    # to be 0 (e.g. a student with no income who's tracking spending only).
    try:
        budget_limit = float(budget_limit)
        income = float(income)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_budget_limit_or_income"}), 400
    if budget_limit < 0 or income < 0:
        return jsonify({"error": "budget_limit_and_income_must_be_non_negative"}), 400

    item = put_budget(
        user_id=request.user_id,
        month=month,
        budget_limit=budget_limit,
        income=income,
    )
    # Don't leak the user_id back to the client — they already know it.
    return jsonify({
        "month": item["month"],
        "budget_limit": item["budget_limit"],
        "income": item["income"],
        "updated_at": item["updated_at"],
    })


@budget_bp.get("/budget")
@require_auth
def get_budget_status():
    """Return the user's budget + spending summary for a month.

    Query:    ?month=2026-09  (defaults to current UTC month)
    Response: { "month", "budget_limit", "income", "total_spent", "savings" }

    If no budget has been set for the month, budget_limit and income are
    returned as 0 — the client can prompt the user to set one. We don't
    404 because the dashboard needs to render even before the user
    configures their first budget.
    """
    month = (request.args.get("month") or "").strip() or _current_month()
    if not _validate_month(month):
        return jsonify({
            "error": "invalid_month",
            "hint": "month must be 'YYYY-MM' (e.g. '2026-09'), zero-padded.",
        }), 400

    budget = get_budget(user_id=request.user_id, month=month)
    budget_limit = float(budget["budget_limit"]) if budget else 0.0
    income = float(budget["income"]) if budget else 0.0

    # Sum this user's expenses whose date falls within the month.
    month_expenses = list_expenses_for_month(request.user_id, month)
    total_spent = 0.0
    for item in month_expenses:
        try:
            total_spent += float(item.get("amount", 0))
        except (TypeError, ValueError):
            continue

    savings = income - total_spent

    return jsonify({
        "month": month,
        "budget_limit": budget_limit,
        "income": income,
        "total_spent": total_spent,
        "savings": savings,
    })
