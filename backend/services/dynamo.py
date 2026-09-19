"""
DynamoDB helpers for the `ExpenseRecords`, `Users` and `Budgets` tables.

Two modes, decided by services/mock_aws.is_mock_mode():
  - mock      — in-memory stubs, so `python app.py` runs with no Docker
  - LocalStack— real boto3 calls with endpoint_url=http://localstack:4566

Decimal handling
----------------
The DynamoDB *resource* API serialises numbers as decimal.Decimal in both
directions:

  - Writing a Python float raises "Float types are not supported".
  - Reading returns Decimal, which Flask's jsonify cannot serialise
    ("Object of type Decimal is not JSON serializable").

Every write here goes through `_to_dynamo()` and every read through
`_to_native()`, so the rest of the backend only ever sees plain ints and
floats. Do not bypass these helpers.
"""

import os
from decimal import Decimal

from services.mock_aws import get_dynamo_resource

_TABLE_NAME = os.environ.get("TABLE_NAME", "ExpenseRecords")
_USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "Users")
_BUDGETS_TABLE_NAME = os.environ.get("BUDGETS_TABLE_NAME", "Budgets")

# Resolve the resource once at import. In mock mode this is the in-memory
# singleton; against LocalStack it is a real boto3 resource whose connection
# pool is reused across warm gunicorn workers.
_dynamo = get_dynamo_resource()
_table = _dynamo.Table(_TABLE_NAME)
_users_table = _dynamo.Table(_USERS_TABLE_NAME)
_budgets_table = _dynamo.Table(_BUDGETS_TABLE_NAME)


# ---------------------------------------------------------------------------
# Decimal <-> native conversion
# ---------------------------------------------------------------------------

def _to_native(obj):
    """Recursively convert Decimal to int/float so jsonify can serialise it.

    Whole-valued Decimals become int (so an amount of 450 renders as 450,
    not 450.0); everything else becomes float. Dicts, lists, sets and tuples
    are walked so nested structures convert too.
    """
    if isinstance(obj, Decimal):
        # Decimal("450") and Decimal("450.00") are both integral.
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, set):
        return [_to_native(v) for v in obj]
    return obj


def _to_dynamo(obj):
    """Recursively convert float to Decimal so put_item accepts it.

    `Decimal(str(x))` rather than `Decimal(x)` — the float constructor keeps
    the full binary expansion (0.1 becomes 0.1000000000000000055511...),
    which DynamoDB rejects for exceeding 38 digits of precision.

    bool is checked before int/float because bool is a subclass of int in
    Python and DynamoDB has a real Boolean type we want to preserve.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dynamo(v) for v in obj]
    return obj


def _scan_all(table):
    """Scan a table, following pagination. DynamoDB caps a Scan page at 1MB."""
    response = table.scan()
    items = list(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return items


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

def list_expenses(user_id=None):
    """Return expense records, optionally filtered by user_id.

    When `user_id` is given, only items whose `user_id` field matches are
    returned — this is the per-user isolation filter the dashboard relies on
    so users never see each other's receipts. When None, returns everything
    (tests and admin paths only; API routes always pass a user_id).
    """
    items = _to_native(_scan_all(_table))
    if user_id is not None:
        items = [i for i in items if i.get("user_id") == user_id]
    return items


def get_expense(expense_id, user_id=None):
    """Fetch a single record by partition key. Returns None if not found.

    When `user_id` is given, also returns None if the record belongs to a
    different user. Returning None rather than 403 means the caller cannot
    distinguish "does not exist" from "belongs to someone else", which
    blocks receipt-ID enumeration.
    """
    response = _table.get_item(Key={"expense_id": expense_id})
    item = response.get("Item")
    if item is None:
        return None
    item = _to_native(item)
    if user_id is not None and item.get("user_id") != user_id:
        return None
    return item


def get_expenses_by_ids(user_id, expense_ids):
    """Fetch several expense records by ID, scoped to one user.

    Used by POST /api/expenses/email. Any id belonging to another user is
    silently excluded; the route then compares counts and returns 403 if
    they do not match, so a caller cannot probe for other users' IDs.
    """
    if not expense_ids:
        return []
    all_items = list_expenses(user_id=user_id)
    id_set = set(expense_ids)
    return [i for i in all_items if i.get("expense_id") in id_set]


def get_total_spent(user_id=None):
    """Sum the `amount` field across a user's expense records."""
    total = 0.0
    for item in list_expenses(user_id=user_id):
        try:
            total += float(item.get("amount", 0))
        except (TypeError, ValueError):
            continue
    return total


def list_expenses_by_event(user_id, event_name):
    """Return a user's expenses for a named event.

    Implemented as a filtered scan rather than a Query. The previous version
    queried an `event_name-index` GSI that was never created by
    localstack/init.py, so any call raised ValidationException. A scan needs
    no index and is correct at demo scale.
    """
    return [i for i in list_expenses(user_id=user_id) if i.get("event_name") == event_name]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(user_id):
    """Fetch a user by partition key. Returns None if not found."""
    response = _users_table.get_item(Key={"user_id": user_id})
    item = response.get("Item")
    return _to_native(item) if item else None


def get_user_by_email(email):
    """Look up a user by email.

    Email is not the partition key, so this scans and filters — fine for a
    handful of accounts. Production would add a GSI on `email`.
    """
    if email is None:
        return None
    email_lower = email.lower()
    for item in _scan_all(_users_table):
        if (item.get("email") or "").lower() == email_lower:
            return _to_native(item)
    return None


def create_user(user):
    """Write a new user record.

    The caller must ensure the email is unique (check get_user_by_email
    first) and that the password is already hashed via services.auth.
    """
    _users_table.put_item(Item=_to_dynamo(user))


# ---------------------------------------------------------------------------
# Budgets — per-user, per-month budget limit + income
# ---------------------------------------------------------------------------

def get_budget(user_id, month):
    """Fetch a user's budget for a month ("YYYY-MM"), or None if unset.

    Callers treat None as budget_limit=0, income=0 so the dashboard renders
    before the user has configured anything.
    """
    response = _budgets_table.get_item(Key={"user_id": user_id, "month": month})
    item = response.get("Item")
    return _to_native(item) if item else None


def put_budget(user_id, month, budget_limit, income):
    """Upsert a user's budget for a month, overwriting any existing record.

    Returns the item with native numbers (not Decimal) so the route handler
    can jsonify it directly.
    """
    from datetime import datetime, timezone

    item = {
        "user_id": user_id,
        "month": month,
        "budget_limit": float(budget_limit),
        "income": float(income),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _budgets_table.put_item(Item=_to_dynamo(item))
    return item


def list_expenses_for_month(user_id, month):
    """Return a user's expenses whose `date` (YYYY-MM-DD) falls in `month`."""
    items = list_expenses(user_id=user_id)
    return [i for i in items if (i.get("date") or "").startswith(month)]
