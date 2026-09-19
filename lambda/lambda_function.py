"""
Smart Campus Expense & Invoice Verifier — ingestion Lambda

Triggered by an S3 ObjectCreated event (or invoked directly by the Flask
backend in LocalStack mode, which is how the docker-compose stack works —
see backend/routes/upload.py).

Pipeline:
  1. Download the receipt image from S3 (`receipts-bucket`).
  2. Run OCR locally via EasyOCR or Tesseract — see lambda/ocr_engine.py.
     No AWS Textract, no Rekognition, no paid API, no network at inference.
  3. Parse vendor / amount / date from the raw OCR text (lambda/parse_ocr.py).
  4. Write a structured record to DynamoDB (`ExpenseRecords`).
  5. Publish to SNS (`ExpenseAlerts`) when the amount breaches BUDGET_LIMIT
     or the receipt is flagged as a duplicate.

Environment variables:
  AWS_ENDPOINT_URL  — http://localstack:4566 inside the compose network,
                      http://localhost:4566 from the host. When unset, boto3
                      talks to real AWS (not used in this project).
  AWS_REGION        — us-east-1
  TABLE_NAME        — DynamoDB table name (default "ExpenseRecords")
  SNS_TOPIC_ARN     — ARN of the alert topic (defaults to the LocalStack ARN
                      for "ExpenseAlerts" under account 000000000000)
  BUDGET_LIMIT      — numeric threshold, default 20000
  OCR_ENGINE        — "easyocr" (default) or "tesseract"
"""

import json
import os
import urllib.parse
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from parse_ocr import parse_ocr_text, parse_s3_key
import ocr_engine

# LocalStack always reports this as the account id. Used to synthesise a
# working SNS topic ARN when SNS_TOPIC_ARN is not supplied, so the alert
# leg of the pipeline is never silently dead just because one env var was
# forgotten in docker-compose.yml.
LOCALSTACK_ACCOUNT_ID = "000000000000"

TABLE_NAME = os.environ.get("TABLE_NAME", "ExpenseRecords")
SNS_TOPIC_NAME = os.environ.get("SNS_TOPIC_NAME", "ExpenseAlerts")
BUDGET_LIMIT = float(os.environ.get("BUDGET_LIMIT", "20000"))


def _region():
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _sns_topic_arn():
    """Resolve the alert topic ARN at call time.

    Read from the env when present; otherwise build the LocalStack ARN from
    the region + topic name. Resolved lazily (not at import) so tests and
    the Flask backend can set the env var after this module is imported.
    """
    configured = os.environ.get("SNS_TOPIC_ARN", "").strip()
    if configured:
        return configured
    return f"arn:aws:sns:{_region()}:{LOCALSTACK_ACCOUNT_ID}:{SNS_TOPIC_NAME}"


def _client_kwargs():
    """Common boto3 kwargs — region plus the LocalStack endpoint override.

    Every client in this project routes through here, which is what keeps
    the "never talk to real AWS" guarantee in one place.
    """
    kwargs = {"region_name": _region()}
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return kwargs


def _make_client(service):
    """Build a boto3 client, returning None instead of raising.

    Client construction can fail at import time outside a configured
    environment (e.g. NoRegionError). Returning None lets the module import
    cleanly; the handler rebuilds lazily on first use.
    """
    try:
        return boto3.client(service, **_client_kwargs())
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"[ingest] Deferring {service} client creation: {exc}")
        return None


def _make_resource(service):
    try:
        return boto3.resource(service, **_client_kwargs())
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"[ingest] Deferring {service} resource creation: {exc}")
        return None


# Module-scope clients so they are reused across warm invocations. The test
# suite and backend/routes/upload.py replace these attributes with mock or
# LocalStack-bound equivalents, so the handler always reads them through the
# module globals rather than capturing them in a closure.
s3 = _make_client("s3")
dynamodb = _make_resource("dynamodb")
sns = _make_client("sns")


def download_image_from_s3(bucket, key):
    """Download the receipt image from S3 to a local temp file.

    Returns the local file path. The Lambda runtime wipes /tmp between
    invocations, so we do not delete the file explicitly.
    """
    import tempfile

    global s3
    if s3 is None:
        s3 = _make_client("s3")

    # Preserve the original extension so PIL / EasyOCR can detect the format.
    suffix = os.path.splitext(key)[-1] or ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    s3.download_file(bucket, key, tmp.name)
    return tmp.name


def run_ocr(image_path):
    """Extract text from a receipt image using the configured local engine.

    Delegates to ocr_engine.run_ocr, which never raises — a failure returns
    "" and the parser substitutes defaults. The test suite monkey-patches
    this name directly, so no OCR engine is needed to run the tests.
    """
    return ocr_engine.run_ocr(image_path)


def _is_duplicate(table, user_id, vendor, amount, date_str, exclude_id=None):
    """Flag a receipt as a duplicate of one already recorded for this user.

    Definition of a duplicate: same user, same vendor, same amount, same
    date. Receipts genuinely can repeat (two coffees on one day), so this
    is a soft flag for review, not a hard reject — the record is still
    written and still shown on the dashboard.

    Scans the table and filters client-side. At campus-demo scale (tens to
    hundreds of records) that is sub-100ms; a production build would add a
    GSI on user_id and Query instead.
    """
    try:
        response = table.scan()
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
    except Exception as exc:
        print(f"[ingest] Duplicate check skipped (scan failed): {exc}")
        return False

    for item in items:
        if exclude_id is not None and item.get("expense_id") == exclude_id:
            continue
        if item.get("user_id") != user_id:
            continue
        if (item.get("vendor") or "") != (vendor or ""):
            continue
        if (item.get("date") or "") != (date_str or ""):
            continue
        try:
            if abs(float(item.get("amount", 0)) - float(amount)) < 0.005:
                return True
        except (TypeError, ValueError):
            continue
    return False


def lambda_handler(event, context):
    """Entry point for an S3 ObjectCreated event.

    Processes the first record in the event. Returns a statusCode/body dict
    shaped like an API Gateway proxy response so the Flask backend can relay
    it straight back to the browser.
    """
    global dynamodb, sns

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    # S3 event notifications URL-encode the key: spaces become "+",
    # parentheses become %28/%29. Passing the raw value to download_file
    # fails, because the real object key is the decoded form.
    raw_key = record["s3"]["object"]["key"]
    key = urllib.parse.unquote_plus(raw_key)

    print(f"[ingest] Received s3://{bucket}/{key}  (raw: {raw_key})")

    # ---- 1. Parse user_id + category out of the S3 key path ----
    # Key format: receipts/{user_id}/{category}/{uuid}_{filename}, set by
    # backend/routes/upload.py. The Lambda never talks to Flask, so the key
    # path is the only carrier for these fields.
    s3_meta = parse_s3_key(key)
    user_id = s3_meta["user_id"]
    category = s3_meta["category"]
    print(f"[ingest] Parsed S3 key: user_id={user_id!r} category={category!r}")

    # ---- 2. Download the receipt image ----
    try:
        image_path = download_image_from_s3(bucket, key)
        print(f"[ingest] Downloaded to {image_path}")
    except Exception as exc:
        print(f"[ingest] S3 download failed for s3://{bucket}/{key}: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "s3_download_failed", "detail": str(exc)}),
        }

    # ---- 3. Run OCR locally ----
    try:
        ocr_text = run_ocr(image_path)
        print(f"[ingest] OCR returned {len(ocr_text or '')} chars ({ocr_engine.get_engine_name()})")
    except Exception as exc:
        # Do not 500 here — we still want a record with defaults so the user
        # sees their upload on the dashboard.
        print(f"[ingest] OCR failed: {exc}")
        ocr_text = ""

    # ---- 4. Parse vendor / amount / date ----
    parsed = parse_ocr_text(ocr_text)
    vendor = parsed.get("vendor") or "Unknown"
    amount = float(parsed.get("amount") or 0.0)
    date_str = parsed.get("date") or datetime.now(timezone.utc).date().isoformat()

    print(f"[ingest] Parsed: vendor={vendor!r} amount={amount} date={date_str}")

    if dynamodb is None:
        dynamodb = _make_resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    # ---- 5. Anomaly detection ----
    over_budget = bool(amount > BUDGET_LIMIT)
    duplicate = _is_duplicate(table, user_id, vendor, amount, date_str)
    flags = []
    if over_budget:
        flags.append("over_budget")
    if duplicate:
        flags.append("duplicate")

    expense_record = {
        "expense_id": str(uuid.uuid4()),
        "user_id": user_id,
        "category": category,
        "event_name": "unassigned",
        "vendor": vendor,
        "amount": amount,
        "date": date_str,
        "s3_key": key,
        "over_budget": over_budget,
        "duplicate": duplicate,
        "flags": flags,
        "ocr_engine": ocr_engine.get_engine_name(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # ---- 6. Persist to DynamoDB ----
    # DynamoDB's Number type requires Decimal — put_item on a float raises
    # "Float types are not supported". We write a Decimal-typed copy and keep
    # the float in expense_record so the HTTP response and the SNS message
    # JSON-serialise cleanly (Decimal is not JSON-native).
    try:
        record_for_dynamo = dict(expense_record)
        record_for_dynamo["amount"] = Decimal(str(amount))
        table.put_item(Item=record_for_dynamo)
        print(f"[ingest] Wrote expense_id={expense_record['expense_id']} to {TABLE_NAME}")
    except Exception as exc:
        print(f"[ingest] DynamoDB put_item failed: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "dynamodb_write_failed", "detail": str(exc)}),
        }

    # ---- 7. Publish an alert for anything flagged ----
    if flags:
        if sns is None:
            sns = _make_client("sns")
        try:
            sns.publish(
                TopicArn=_sns_topic_arn(),
                Subject=f"Expense flagged: {', '.join(flags)}",
                Message=json.dumps(expense_record, indent=2),
            )
            print(f"[ingest] Published alert ({', '.join(flags)}) for {expense_record['expense_id']}")
        except Exception as exc:
            # A failed alert must not fail the ingest — the record is already
            # in DynamoDB and the dashboard will still show it.
            print(f"[ingest] SNS publish failed (non-fatal): {exc}")

    return {
        "statusCode": 200,
        "body": json.dumps(expense_record),
    }
