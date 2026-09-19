#!/usr/bin/env python3
"""LocalStack initialisation — runs once, after LocalStack reports healthy.

Creates:
  - S3 bucket:        receipts-bucket  (+ CORS, so the browser can PUT to it)
  - DynamoDB tables:  ExpenseRecords, Users, Budgets
  - SNS topic:        ExpenseAlerts

No demo data is seeded — the app starts empty and users register via the UI.
Every step is idempotent, so re-running the container is safe.

Region is us-east-1 throughout. That matters for the bucket: us-east-1 is
the only region where CreateBucket must NOT be given a
CreateBucketConfiguration.LocationConstraint. Passing one raises
InvalidLocationConstraint — which is exactly what happens if you copy a
create_bucket call written for another region.
"""

import json
import os
import sys
import time

import boto3
from botocore.client import Config

LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localstack:4566")
REGION = os.environ.get("AWS_REGION", "us-east-1")

BUCKET = os.environ.get("S3_BUCKET", "receipts-bucket")
EXPENSES_TABLE = os.environ.get("TABLE_NAME", "ExpenseRecords")
USERS_TABLE = os.environ.get("USERS_TABLE_NAME", "Users")
BUDGETS_TABLE = os.environ.get("BUDGETS_TABLE_NAME", "Budgets")
SNS_TOPIC_NAME = os.environ.get("SNS_TOPIC_NAME", "ExpenseAlerts")

# Origins the browser may PUT receipts from. 5173 is the nginx-served build,
# 5174/5175 cover Vite auto-incrementing when a port is taken.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", REGION)


def wait_for_localstack(timeout=90):
    """Block until LocalStack answers its health endpoint."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    health_url = f"{LOCALSTACK_ENDPOINT}/_localstack/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=3) as resp:
                if resp.status == 200:
                    print(f"[init] LocalStack healthy at {LOCALSTACK_ENDPOINT}")
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        print(f"[init] Waiting for LocalStack at {LOCALSTACK_ENDPOINT}...")
        time.sleep(2)
    print("[init] LocalStack did not become healthy in time", file=sys.stderr)
    return False


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name=REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def create_bucket(s3):
    """Create the receipts bucket, then apply a CORS policy.

    us-east-1 takes no LocationConstraint — see the module docstring.
    """
    try:
        s3.create_bucket(Bucket=BUCKET)
        print(f"[init] Created S3 bucket: {BUCKET}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"[init] S3 bucket {BUCKET} already exists — skipping")
    except s3.exceptions.BucketAlreadyExists:
        print(f"[init] S3 bucket {BUCKET} already exists — skipping")
    except Exception as exc:
        print(f"[init] Bucket creation failed: {exc}", file=sys.stderr)
        raise

    # CORS is required because the browser PUTs the receipt image straight
    # to LocalStack via a presigned URL, from origin :5173 to origin :4566.
    # Without this the preflight fails and the upload never leaves the tab.
    cors = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["PUT", "GET", "HEAD"],
                "AllowedOrigins": ALLOWED_ORIGINS,
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3000,
            }
        ]
    }
    try:
        s3.put_bucket_cors(Bucket=BUCKET, CORSConfiguration=cors)
        print(f"[init] Applied CORS to {BUCKET}: {', '.join(ALLOWED_ORIGINS)}")
    except Exception as exc:
        print(f"[init] put_bucket_cors failed (uploads from the browser will "
              f"be blocked): {exc}", file=sys.stderr)


def create_tables(dynamo):
    tables = [
        {
            "TableName": EXPENSES_TABLE,
            "AttributeDefinitions": [{"AttributeName": "expense_id", "AttributeType": "S"}],
            "KeySchema": [{"AttributeName": "expense_id", "KeyType": "HASH"}],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": USERS_TABLE,
            "AttributeDefinitions": [{"AttributeName": "user_id", "AttributeType": "S"}],
            "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": BUDGETS_TABLE,
            "AttributeDefinitions": [
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "month", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "month", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]
    for tbl in tables:
        name = tbl["TableName"]
        try:
            dynamo.create_table(**tbl)
            print(f"[init] Created DynamoDB table: {name}")
        except dynamo.exceptions.ResourceInUseException:
            print(f"[init] DynamoDB table {name} already exists — skipping")
        except Exception as exc:
            print(f"[init] Table creation failed for {name}: {exc}", file=sys.stderr)
            raise

    for tbl in tables:
        name = tbl["TableName"]
        dynamo.get_waiter("table_exists").wait(TableName=name)
        print(f"[init] Table {name} is ACTIVE")


def create_topic(sns):
    """Create the alert topic. create_topic is idempotent in SNS — calling
    it for an existing name returns the same ARN rather than erroring."""
    topic = sns.create_topic(Name=SNS_TOPIC_NAME)
    arn = topic["TopicArn"]
    print(f"[init] SNS topic ready: {arn}")

    # Subscribe an email endpoint so the alert is observable. LocalStack
    # does not deliver mail; the subscription exists so you can see the
    # published message with:
    #   awslocal sns list-subscriptions
    try:
        sns.subscribe(
            TopicArn=arn,
            Protocol="email",
            Endpoint=os.environ.get("ALERT_EMAIL", "finance-office@campus.local"),
        )
        print("[init] Subscribed a demo email endpoint to ExpenseAlerts")
    except Exception as exc:
        print(f"[init] SNS subscribe skipped (non-fatal): {exc}")
    return arn


def main():
    if not wait_for_localstack():
        sys.exit(1)

    s3 = _s3_client()
    dynamo = boto3.client("dynamodb", endpoint_url=LOCALSTACK_ENDPOINT, region_name=REGION)
    sns = boto3.client("sns", endpoint_url=LOCALSTACK_ENDPOINT, region_name=REGION)

    create_bucket(s3)
    create_tables(dynamo)
    arn = create_topic(sns)

    print("[init] ------------------------------------------------------")
    print(f"[init] Bucket:  {BUCKET}")
    print(f"[init] Tables:  {EXPENSES_TABLE}, {USERS_TABLE}, {BUDGETS_TABLE}")
    print(f"[init] Topic:   {arn}")
    print("[init] Setup complete. Register an account at http://localhost:5173")
    print("[init] ------------------------------------------------------")


if __name__ == "__main__":
    main()
