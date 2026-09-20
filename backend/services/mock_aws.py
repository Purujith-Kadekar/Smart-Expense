"""
In-memory mock for AWS services (DynamoDB, S3 presigned URLs, SNS).

Used when MOCK_AWS=1 is set in the environment — lets the Flask backend
start and respond to all endpoints without any real AWS credentials or
network access. Indispensable for local testing, CI, and demo fallback.

The mock is intentionally minimal: it implements exactly the surface area
the real services/dynamo.py and services/s3.py use, no more. Switching
between mock and real is done via environment variable so the production
code path is unchanged.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone


# When set, the in-memory mock persists every write to this JSON file and
# reloads it on the next start — so `python app.py` (no Docker, no AWS
# account) keeps accounts, budgets and receipts between restarts.
_PERSIST_FILE = os.environ.get("MOCK_PERSIST_FILE", "").strip()


class _MockDynamoTable:
    """In-memory stand-in for a DynamoDB Table resource.

    Implements the methods actually called from services/dynamo.py:
    `scan`, `get_item`, `put_item`, `query`. Persists items in a dict
    keyed by the table's partition key (and optionally a sort key).

    The partition/sort key names are configurable so the same class can
    back:
      - `Expenses` (partition key `expense_id`, no sort key)
      - `Users`    (partition key `user_id`, no sort key)
      - `Budgets`  (partition key `user_id`, sort key `month`)
    """

    def __init__(self, name, partition_key, sort_key=None):
        self.name = name
        self.partition_key = partition_key
        self.sort_key = sort_key
        self._items = {}  # key: partition_key_value OR (pk, sk) tuple
        self._lock = threading.Lock()

    def _item_key(self, Item):
        """Compute the dict key used to store an item — includes the sort
        key value when the table has one, so multiple items with the same
        partition key (e.g. a user's budgets for different months) don't
        clobber each other."""
        pk = Item[self.partition_key]
        if self.sort_key and self.sort_key in Item:
            return (pk, Item[self.sort_key])
        return pk

    def _lookup_key(self, Key):
        """Compute the dict key from a get_item/query Key dict."""
        pk = Key[self.partition_key]
        if self.sort_key and self.sort_key in Key:
            return (pk, Key[self.sort_key])
        return pk

    def put_item(self, Item):
        with self._lock:
            self._items[self._item_key(Item)] = dict(Item)
        if _PERSIST_FILE:
            _snapshot_to_disk()

    def get_item(self, Key):
        with self._lock:
            item = self._items.get(self._lookup_key(Key))
            return {"Item": dict(item)} if item else {}

    def scan(self, ExclusiveStartKey=None):
        with self._lock:
            items = [dict(v) for v in self._items.values()]
            return {"Items": items}

    def query(self, IndexName=None, KeyConditionExpression=None, **kwargs):
        # Real DynamoDB Query filters by partition key (and optionally a
        # sort-key condition). In mock mode we don't parse the
        # KeyConditionExpression object — we just return all items whose
        # partition key matches. The caller (services/dynamo.py) filters
        # further if needed.
        with self._lock:
            items = [dict(v) for v in self._items.values()]
        return {"Items": items}


# Map table name -> (partition_key, sort_key). The names are read from the
# same env vars services/dynamo.py uses, so renaming a table in
# docker-compose.yml cannot desync the mock's key schema from the real one.
_EXPENSES_TABLE = os.environ.get("TABLE_NAME", "ExpenseRecords")
_USERS_TABLE = os.environ.get("USERS_TABLE_NAME", "Users")
_BUDGETS_TABLE = os.environ.get("BUDGETS_TABLE_NAME", "Budgets")
_FINGERPRINTS_TABLE = os.environ.get("FINGERPRINTS_TABLE_NAME", "ReceiptFingerprints")

_TABLE_KEYS = {
    _EXPENSES_TABLE: ("expense_id", None),
    _USERS_TABLE: ("user_id", None),
    _BUDGETS_TABLE: ("user_id", "month"),
    # Fraud-detection table — partition key is the SHA-256 file hash.
    # If this entry is missing, the mock falls back to ("id", None)
    # and put_receipt_fingerprint() raises KeyError (caught by the
    # try/except in dynamo.py, but means duplicate-detection can't
    # store fingerprints in mock mode — silently degrading fraud
    # detection).
    _FINGERPRINTS_TABLE: ("file_hash", None),
    # Legacy aliases so a stale env var or an old test fixture still gets
    # the right key schema instead of silently falling back to "id".
    "ExpenseRecords": ("expense_id", None),
    "Expenses": ("expense_id", None),
    "Users": ("user_id", None),
    "Budgets": ("user_id", "month"),
}
_TABLE_PARTITION_KEYS = {name: pk for name, (pk, _) in _TABLE_KEYS.items()}


class _MockDynamoResource:
    """Stand-in for boto3.resource('dynamodb'). Returns the same Table
    object on every call so the in-memory state persists."""

    def __init__(self):
        self._tables = {}

    def Table(self, name):
        if name not in self._tables:
            partition_key, sort_key = _TABLE_KEYS.get(name, ("id", None))
            table = _MockDynamoTable(name, partition_key, sort_key)
            if _PERSIST_FILE:
                _hydrate_from_disk(table)
            self._tables[name] = table
        return self._tables[name]


# ---------------------------------------------------------------------------
# File persistence (MOCK_PERSIST_FILE)
# ---------------------------------------------------------------------------
#
# Items stored via put_item have already been through dynamo._to_dynamo(),
# so they contain Decimal values — JSON has no Decimal. We round-trip them
# through a tagged dict ({"__decimal__": "123.45"}) so precision survives
# the save/load cycle exactly.

_PERSIST_LOCK = threading.Lock()
_PERSIST_CACHE = None  # parsed file contents, loaded once per process
_DECIMAL_TAG = "__decimal__"


def _encode_for_disk(value):
    """Convert an item (dict/list/Decimal/...) into JSON-safe structures."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return {_DECIMAL_TAG: str(value)}
    if isinstance(value, dict):
        return {k: _encode_for_disk(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_for_disk(v) for v in value]
    return value


def _decode_from_disk(value):
    """Inverse of _encode_for_disk — restores Decimal from the tag."""
    from decimal import Decimal

    if isinstance(value, dict):
        if set(value.keys()) == {_DECIMAL_TAG}:
            return Decimal(str(value[_DECIMAL_TAG]))
        return {k: _decode_from_disk(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_from_disk(v) for v in value]
    return value


def _read_persist_file():
    """Parse the persist file once and cache it. Returns {} when unset or
    unreadable (a corrupt file must never crash the backend — worst case we
    start from an empty store, same as without persistence)."""
    global _PERSIST_CACHE
    if not _PERSIST_FILE:
        return {}
    if _PERSIST_CACHE is None:
        try:
            with open(_PERSIST_FILE, "r", encoding="utf-8") as fh:
                _PERSIST_CACHE = json.load(fh)
        except FileNotFoundError:
            _PERSIST_CACHE = {}
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[mock-aws] MOCK_PERSIST_FILE unreadable ({exc}) — starting empty")
            _PERSIST_CACHE = {}
    return _PERSIST_CACHE


def _hydrate_from_disk(table):
    """Load a newly created mock table's items from the persist file."""
    data = _read_persist_file()
    items = (data.get("tables") or {}).get(table.name) or []
    with table._lock:
        for raw in items:
            item = _decode_from_disk(raw)
            try:
                table._items[table._item_key(item)] = dict(item)
            except KeyError:
                # Item without the partition key — skip rather than crash.
                continue


def _snapshot_to_disk():
    """Atomically write every mock table's items to the persist file.

    Called after each put_item — hackathon write rates make this cheap, and
    write-through means a Ctrl-C can never lose acknowledged data. The
    tmp-file + os.replace rename is atomic on POSIX and Windows, so a crash
    mid-write can never corrupt the previous snapshot.
    """
    if not _PERSIST_FILE:
        return
    with _PERSIST_LOCK:
        tables = {}
        for name, table in _DYNAMO._tables.items():
            with table._lock:
                tables[name] = [_encode_for_disk(dict(v)) for v in table._items.values()]
        payload = {
            "version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "tables": tables,
        }
        try:
            directory = os.path.dirname(os.path.abspath(_PERSIST_FILE))
            os.makedirs(directory, exist_ok=True)
            tmp_path = _PERSIST_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp_path, _PERSIST_FILE)
        except OSError as exc:
            # Never let a persistence hiccup fail the actual API write.
            print(f"[mock-aws] could not persist to {_PERSIST_FILE}: {exc}")


class _MockSNSClient:
    """Captures published SNS messages in a list — tests can inspect them
    to verify over-budget alerts fired without standing up a real topic."""

    published = []

    def publish(self, TopicArn, Subject, Message):
        record = {
            "TopicArn": TopicArn,
            "Subject": Subject,
            "Message": Message,
            "MessageId": str(uuid.uuid4()),
        }
        self.published.append(record)
        return record


class _MockS3Client:
    """Deterministic fake S3 so the upload flow can be exercised with no
    bucket. Implements exactly the surface services/s3.py and the Lambda
    use: generate_presigned_url, head_object, download_file."""

    def generate_presigned_url(self, operation, Params, ExpiresIn=300, HttpMethod=None):
        bucket = Params.get("Bucket", "mock-bucket")
        key = Params.get("Key", "mock-key")
        return f"https://mock-s3.local/{bucket}/{key}?expires={ExpiresIn}&op={operation}&method={HttpMethod or 'GET'}"

    def head_object(self, Bucket, Key):
        """Always report the object as present. In mock mode nothing was
        ever really uploaded, and failing here would block the trigger-ocr
        path that mock mode exists to exercise."""
        return {"ContentLength": 0, "ContentType": "image/jpeg"}

    def download_file(self, Bucket, Key, Filename):
        """No-op — the Lambda's OCR step is patched out in mock mode, so
        the file is never opened."""
        return None


class _MockSESClient:
    """Captures sent emails in a list — tests can inspect them to verify
    the right recipient / subject / body was used without sending real
    email via SES (which would require a verified sender identity).

    Follows the same capture-in-a-list pattern as _MockSNSClient.
    """

    def __init__(self):
        self.sent = []

    def send_email(self, Source, Destination, Message, **kwargs):
        """Mirror of boto3 SES `send_email` signature — we only capture
        the fields our route handler actually uses (Source, Destination.To,
        Message.Subject.Data, Message.Body.Html.Data)."""
        to_addrs = (Destination or {}).get("ToAddresses", [])
        subject = ((Message or {}).get("Subject") or {}).get("Data", "")
        html_body = (((Message or {}).get("Body") or {}).get("Html") or {}).get("Data", "")
        text_body = (((Message or {}).get("Body") or {}).get("Text") or {}).get("Data", "")
        record = {
            "Source": Source,
            "To": list(to_addrs),
            "Subject": subject,
            "HtmlBody": html_body,
            "TextBody": text_body,
            "MessageId": str(uuid.uuid4()),
        }
        self.sent.append(record)
        return {"MessageId": record["MessageId"]}


# Module-level singletons — created once, referenced by services via the
# factory functions below.
_DYNAMO = _MockDynamoResource()
_SNS = _MockSNSClient()
_S3 = _MockS3Client()
_SES = _MockSESClient()


def is_mock_mode():
    """Decide whether to use the in-memory mock AWS layer or real boto3.

    Resolution order:
      1. If MOCK_AWS env var is set explicitly → honour it (truthy = mock,
         falsy = real). This is the override knob — `MOCK_AWS=0` forces
         real AWS even when no credentials are configured.
      2. Otherwise, auto-detect: look for AWS credentials in the standard
         locations (env vars, ~/.aws/credentials, ~/.aws/config). If none
         are found, default to mock mode. This makes `python app.py`
         "just work" on a fresh clone without any env-var setup.
      3. If credentials ARE present, default to real AWS — mock is opt-in.

    We deliberately do NOT call `boto3.Session().get_credentials()` here,
    because boto3's credential provider chain tries IMDS (the EC2 instance
    metadata service at 169.254.169.254) on every call. On a non-EC2
    machine without credentials, IMDS lookup hangs for ~5 seconds before
    failing — which would make Flask startup slow and might block on
    some networks. The file/env-var check below is fast and complete for
    local dev.
    """
    env_value = os.environ.get("MOCK_AWS", "").strip().lower()
    if env_value:
        # Explicit override — truthy means mock, falsy means real.
        return env_value in {"1", "true", "yes", "on"}

    # Auto-detect: scan the standard local credential sources without
    # touching boto3's IMDS chain.
    # Source 1: env vars set by `aws configure` or CI.
    has_env_creds = bool(
        os.environ.get("AWS_ACCESS_KEY_ID")
        and os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    # Source 2: shared credentials file (~/.aws/credentials).
    home = os.path.expanduser("~")
    creds_file = os.path.join(home, ".aws", "credentials")
    config_file = os.path.join(home, ".aws", "config")
    has_shared_creds = os.path.isfile(creds_file) and os.path.getsize(creds_file) > 0
    has_config = os.path.isfile(config_file) and os.path.getsize(config_file) > 0

    if has_env_creds or has_shared_creds or has_config:
        return False

    # No credentials anywhere → mock mode kicks in so the dashboard works
    # on first clone. This is what makes local dev zero-config.
    return True


def get_dynamo_resource():
    """Factory — returns the mock or a real boto3 dynamodb resource.

    In docker-compose mode, MOCK_AWS is unset and AWS_ENDPOINT_URL points
    at LocalStack — boto3 uses real AWS calls but they go to LocalStack.
    """
    if is_mock_mode():
        return _DYNAMO
    import boto3
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)


def get_sns_client():
    if is_mock_mode():
        return _SNS
    import boto3
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("sns", **kwargs)


def _s3_config():
    """botocore Config shared by both S3 clients.

    - signature_version="s3v4": LocalStack expects SigV4 presigned URLs.
      botocore still defaults some S3 paths to SigV2, which LocalStack
      rejects with SignatureDoesNotMatch.
    - addressing_style="path": the default virtual-host style builds
      http://receipts-bucket.localhost:4566/... , and no browser or
      container resolves a bucket name as a subdomain of localhost.
    """
    from botocore.client import Config
    return Config(signature_version="s3v4", s3={"addressing_style": "path"})


def get_s3_client():
    """S3 client for server-side calls — points at the in-cluster endpoint."""
    if is_mock_mode():
        return _S3
    import boto3
    kwargs = {
        "region_name": os.environ.get("AWS_REGION", "us-east-1"),
        "config": _s3_config(),
    }
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def get_presigning_s3_client():
    """S3 client used ONLY to sign URLs that the browser will call.

    Points at AWS_PUBLIC_ENDPOINT_URL (http://localhost:4566) rather than
    the compose-internal hostname, because a SigV4 signature covers the
    Host header — you cannot sign for `localstack` and then send the
    request to `localhost`. Falls back to AWS_ENDPOINT_URL when the public
    override is unset, which is the correct behaviour when the backend
    itself runs on the host.
    """
    if is_mock_mode():
        return _S3
    import boto3
    kwargs = {
        "region_name": os.environ.get("AWS_REGION", "us-east-1"),
        "config": _s3_config(),
    }
    endpoint = (
        os.environ.get("AWS_PUBLIC_ENDPOINT_URL")
        or os.environ.get("AWS_ENDPOINT_URL")
    )
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def get_ses_client():
    if is_mock_mode():
        return _SES
    import boto3
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("ses", **kwargs)


# ---------------------------------------------------------------------------
# Storage-mode introspection — powers GET /api/system/storage and the
# frontend storage banner, so "why isn't my data persisting?" is answerable
# at a glance instead of guesswork.
# ---------------------------------------------------------------------------

def storage_mode_info():
    """Describe which storage backend the services are wired to right now.

    Returns a dict:
      mode        "mock"       — in-memory dicts (nothing survives restart
                                 unless persist_file is set)
                  "localstack" — real boto3 against an AWS-compatible local
                                 endpoint (LocalStack, moto, dynamodb-local)
                  "aws"        — real boto3 against real Amazon DynamoDB
      endpoint    the AWS_ENDPOINT_URL in use, or None for real AWS
      persistent  whether data survives a backend restart in this mode
      persist_file  mock mode only — the MOCK_PERSIST_FILE path in use
    """
    mock = is_mock_mode()
    endpoint = (os.environ.get("AWS_ENDPOINT_URL") or "").strip() or None
    persist_file = _PERSIST_FILE or None
    if mock:
        mode = "mock"
    elif endpoint:
        mode = "localstack"
    else:
        mode = "aws"

    if mode == "aws":
        persistent = True
    elif mode == "mock":
        persistent = bool(persist_file)
    else:
        # LocalStack snapshots require Pro (PERSISTENCE is ignored by the
        # Community image — state lives only in the container's memory and
        # dies on stop/down/restart).
        persistent = os.environ.get("PERSISTENCE", "0").strip().lower() in {"1", "true", "yes", "on"}

    return {
        "mode": mode,
        "endpoint": endpoint,
        "persistent": persistent,
        "persist_file": persist_file,
    }


def mock_item_counts():
    """Item count per mock table (mock mode only). Ensures each table object
    exists (and is hydrated from the persist file) before counting."""
    counts = {}
    for name in {_EXPENSES_TABLE, _USERS_TABLE, _BUDGETS_TABLE, _FINGERPRINTS_TABLE}:
        table = _DYNAMO.Table(name)
        with table._lock:
            counts[name] = len(table._items)
    return counts
