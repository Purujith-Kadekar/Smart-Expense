#!/usr/bin/env python3
"""LocalStack initialisation — runs once, after LocalStack reports healthy.

Creates:
  - S3 bucket:        receipts-bucket  (+ CORS, so the browser can PUT to it)
  - DynamoDB tables:  ExpenseRecords, Users, Budgets, ReceiptFingerprints
  - SNS topic:        ExpenseAlerts

No demo data is seeded — the app starts empty and users register via the UI.
Every step is idempotent, so re-running the container is safe.

Region is us-east-1 throughout. That matters for the bucket: us-east-1 is
the only region where CreateBucket must NOT be given a
CreateBucketConfiguration.LocationConstraint. Passing one raises
InvalidLocationConstraint — which is exactly what happens if you copy a
create_bucket call written for another region. (Outside us-east-1, set
AWS_REGION: the code below adds the LocationConstraint when needed.)

Usage:
  python init.py           — create resources in LocalStack (default)
  python init.py --aws     — create resources in REAL AWS (durable storage:
                             accounts, budgets and receipts survive
                             restarts; DynamoDB free tier covers this).
                             Requires `aws configure` credentials.
"""

import argparse
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
FINGERPRINTS_TABLE = os.environ.get("FINGERPRINTS_TABLE_NAME", "ReceiptFingerprints")
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


def _s3_client(use_aws=False):
    """S3 client for the chosen target.

    LocalStack: SigV4 + path-style (virtual-host style would build
    receipts-bucket.localhost:4566, which resolves nowhere).
    Real AWS: default addressing (virtual-host style is the standard there).
    """
    if use_aws:
        return boto3.client("s3", region_name=REGION)
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
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=BUCKET)
        else:
            s3.create_bucket(
                Bucket=BUCKET,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
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
        # ReceiptFingerprints — fraud-detection table. Partition key is
        # the SHA-256 of the original file bytes (string), so an exact-
        # duplicate lookup is a single get_item. The perceptual hash
        # (phash) is stored as a Number; the duplicate checker scans
        # the table and computes Hamming distance in-process — fine at
        # demo scale. At any real scale, add a GSI on a `phash_bucket`
        # attribute (top 16 bits of phash) for sublinear locality-
        # sensitive hashing. The table is optional — the fraud pipeline
        # tolerates its absence (skips cross-receipt duplicate
        # detection and falls back to the in-process scan of
        # ExpenseRecords).
        {
            "TableName": FINGERPRINTS_TABLE,
            "AttributeDefinitions": [
                {"AttributeName": "file_hash", "AttributeType": "S"},
            ],
            "KeySchema": [{"AttributeName": "file_hash", "KeyType": "HASH"}],
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
            Endpoint=os.environ.get("ALERT_EMAIL", "alerts@outlay.local"),
        )
        print("[init] Subscribed a demo email endpoint to ExpenseAlerts")
    except Exception as exc:
        print(f"[init] SNS subscribe skipped (non-fatal): {exc}")
    return arn


def main():
    parser = argparse.ArgumentParser(
        description="Create the Outlay AWS resources (bucket, tables, topic)."
    )
    parser.add_argument(
        "--aws",
        action="store_true",
        help="create the resources in REAL AWS instead of LocalStack — durable "
             "storage for accounts/budgets/receipts (uses your `aws configure` "
             "credentials; DynamoDB + S3 free tiers cover this usage)",
    )
    args = parser.parse_args()

    if args.aws:
        print("[init] --aws mode: creating resources in REAL AWS")
        print(f"[init] Region: {REGION}")
        print("[init] Make sure `aws configure` has run — real credentials are used.")
        s3 = _s3_client(use_aws=True)
        dynamo = boto3.client("dynamodb", region_name=REGION)
        sns = boto3.client("sns", region_name=REGION)
    else:
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
    print(f"[init] Tables:  {EXPENSES_TABLE}, {USERS_TABLE}, {BUDGETS_TABLE}, {FINGERPRINTS_TABLE}")
    print(f"[init] Topic:   {arn}")
    if args.aws:
        print("[init] REAL AWS mode — then point the backend at it:")
        print("[init]   backend/.env: comment out AWS_ENDPOINT_URL and")
        print("[init]   AWS_PUBLIC_ENDPOINT_URL, and set MOCK_AWS=0")
    else:
        print("[init] Setup complete. Register an account at http://localhost:5173")
    print("[init] ------------------------------------------------------")


if __name__ == "__main__":
    main()
