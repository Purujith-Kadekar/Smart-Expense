# Outlay

A local-first expense tracker. Upload a receipt photo, OCR reads the
vendor / amount / date / currency, the amount is converted to INR at the
live exchange rate (then frozen), the record lands in DynamoDB, and anything
flagged (over budget or a suspected duplicate) publishes an SNS alert.

Everything runs on your machine. No AWS account, no credentials, no paid
API. LocalStack stands in for S3, DynamoDB, SNS and SES; OCR runs locally
via EasyOCR or Tesseract — never Textract or Rekognition.

## Run it

```bash
docker-compose up --build
```

Then open <http://localhost:5173> and register an account. The app starts
empty.

First build takes 5–10 minutes and produces a ~2 GB backend image, because
EasyOCR pulls in CPU PyTorch and its model weights are baked into the image
so the container needs no network at runtime. For a ~350 MB image and a
much faster build, switch both places that name the engine in
`docker-compose.yml`:

```yaml
    build:
      args:
        OCR_ENGINE: tesseract
    environment:
      - OCR_ENGINE=tesseract
```

## Architecture

```
browser ──PUT (presigned)──> LocalStack S3 (receipts-bucket)
   │                                  │
   └──POST /api/expenses/trigger-ocr──┘
                  │
            Flask backend ── imports ──> lambda_function.lambda_handler
                                              │
                            local OCR ────────┤
                                              ├──> DynamoDB (ExpenseRecords)
                                              └──> SNS (ExpenseAlerts) if flagged
```

The backend invokes the Lambda handler in-process instead of relying on an
S3 → Lambda notification. LocalStack Community's notification delivery is
unreliable, and an in-process call is faster and removes the need to mount
the Docker socket.

### Why two AWS endpoints

`docker-compose.yml` sets both:

| Variable | Value | Used by |
|---|---|---|
| `AWS_ENDPOINT_URL` | `http://localstack:4566` | backend → LocalStack |
| `AWS_PUBLIC_ENDPOINT_URL` | `http://localhost:4566` | signing presigned URLs |

A presigned URL is handed to the browser, and the browser has no DNS entry
for `localstack`. You cannot sign for one host and send to another either —
SigV4 covers the `Host` header, so rewriting the hostname afterwards gives
`SignatureDoesNotMatch`. Hence a separate signing client.

S3 is also forced to path-style addressing; the default virtual-host style
builds `receipts-bucket.localhost:4566`, which resolves nowhere.

### Decimal, not float

The DynamoDB resource API rejects Python `float` on write
(`Float types are not supported`) and returns `Decimal` on read
(`Object of type Decimal is not JSON serializable`). Every read and write in
`backend/services/dynamo.py` goes through `_to_native()` / `_to_dynamo()`.
Do not bypass them.

## Currency policy — everything is ₹ (INR)

The app has exactly one display currency: the rupee. Foreign-currency
receipts go through a **convert-once-then-freeze** pipeline:

1. OCR detects the receipt's currency (₹/Rs, $/USD, €/EUR, £/GBP, ¥/JPY).
2. At ingest time the Lambda fetches the **live** USD/EUR/...→INR rate
   (free keyless API: `https://open.er-api.com/v6/latest/INR`, cached 60s,
   3s timeout) and converts the amount to INR **once**.
3. The record stores the audit trail — `original_amount`, `currency`,
   `fx_rate`, `fx_source`, `fx_fetched_at` — and the frozen INR value in
   `amount`. It is **never re-converted**: if the market moves tomorrow,
   yesterday's receipt keeps yesterday's rate.
4. Every total the dashboard computes (budget status, income vs spent,
   category breakdown, email bills) sums `amount`, so everything renders
   in ₹ with zero per-currency juggling.

If the rate API is unreachable (offline demo), a built-in fallback table
is used and records are stamped `fx_source="fallback"` — the fallback is
visible on the record itself, never silent.

Conversion is fully automatic and invisible: the rate is fetched by the
ingestion pipeline at upload time — there is no exchange-rates panel,
widget or API anywhere in the app. The only rate a user ever sees is the
frozen one stamped on their own receipts.

## Storage & persistence — why data can "not store"

Accounts (Users), budgets (Budgets) and receipts (ExpenseRecords) live in
Amazon DynamoDB tables; receipt images live in S3. The backend talks to
them through plain boto3 — **which DynamoDB you actually get depends on how
you run it**:

| Mode | When it happens | Survives a restart? |
|---|---|---|
| In-memory mock | `python app.py` with no AWS credentials and `MOCK_AWS` unset (auto-detect), or `MOCK_AWS=1` | **NO** — everything vanishes when the process exits |
| File-backed mock | `MOCK_AWS=1` + `MOCK_PERSIST_FILE=outlay-dev-state.json` | **YES** — snapshot written after every change, reloaded on start |
| LocalStack | `docker-compose up` (default) | **NO on Community** — state is container memory; `down/stop/restart` wipes it. Pro honours `PERSISTENCE=1` snapshots |
| Real Amazon DynamoDB | `MOCK_AWS=0`, `AWS_ENDPOINT_URL` unset, real credentials | **YES** — this is actual AWS durability |

If it looks like "the budget and accounts aren't storing", it is almost
always one of:

1. **The stack/process was restarted** in a non-durable mode above — the
   writes succeeded, then the store was wiped.
2. **Storage is unreachable** — LocalStack not running, tables never created,
   or a wrong `AWS_ENDPOINT_URL`. Every write now fails with a clean JSON
   `503 storage_unavailable` carrying the real cause (this used to be an
   opaque HTML 500).
3. **Host-mode uploads died before ingest** — fixed: `trigger-ocr` used to
   hard-code the Docker-only path `/lambda`, so on `python app.py` every
   receipt uploaded to S3 but never became an expense record.

Diagnose in one glance:

```bash
curl http://localhost:5000/api/system/storage
```

It reports the active mode, the endpoint, per-table reachability (2-3s
timeouts, no retries) and S3 — no auth required, so it works even when
login itself is broken. The Dashboard and Settings pages also render a
storage banner with the same information.

### Durable local dev — no Docker, no AWS account

```
MOCK_AWS=1
MOCK_PERSIST_FILE=./outlay-dev-state.json
```
in `backend/.env`. Accounts, budgets and receipts then survive restarts
via a JSON snapshot (atomic write after every change). OCR is still stubbed
in this mode — use it for UI/data plumbing, not parser accuracy.

### Durable demo with real Amazon DynamoDB

Yes — the app can use the real thing (that is the "amazondb" it always
used, just pointed at a local emulator by default):

```bash
aws configure                                   # real credentials
python localstack/init.py --aws                 # creates the 3 tables + bucket + CORS
# backend/.env: comment out AWS_ENDPOINT_URL and AWS_PUBLIC_ENDPOINT_URL,
# and set MOCK_AWS=0
python app.py
```

DynamoDB + S3 free tiers cover a hackathon demo comfortably. Receipts PUT
directly to real S3 from the browser (presigned, CORS applied by init),
ingestion runs in-process, and every record is durable.

## Layout

```
backend/            Flask API — auth, uploads, expenses, budgets
  services/         boto3 clients, DynamoDB + S3 + SES helpers
  routes/           blueprints, all mounted under /api
lambda/             ingestion handler, OCR engine, receipt text parser,
                    fx.py (automatic INR conversion at ingest)
localstack/         one-shot script: bucket + CORS, tables, SNS topic
frontend/           React + Vite, served by nginx in compose
```

## API

All routes are under `/api` and require `Authorization: Bearer <jwt>`
except `register`, `login`, and `/health`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/register` | create account, returns a JWT |
| POST | `/api/login` | authenticate, returns a JWT |
| POST | `/api/upload-url` | presigned S3 PUT URL (`filename`, `category`) |
| POST | `/api/expenses/trigger-ocr` | run the ingestion handler for an `s3_key` (converts to ₹, freezes rate) |
| GET | `/api/expenses` | the caller's receipts (amounts in INR) |
| GET | `/api/expenses/<id>` | one receipt, ownership-checked |
| POST | `/api/expenses/email` | email selected receipts as a bill via SES (INR) |
| GET | `/api/budget?month=YYYY-MM` | limit, income, total spent, savings (INR) |
| POST | `/api/budget` | upsert a monthly budget |
| GET | `/api/system/storage` | storage diagnostics: active mode + table/S3 reachability (no auth) |
| GET | `/health` | liveness probe, no auth |

Categories are `college`, `mess`, `event`, `other`.

## Inspecting state

```bash
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
AWS="aws --endpoint-url=http://localhost:4566"

$AWS s3 ls s3://receipts-bucket --recursive
$AWS dynamodb scan --table-name ExpenseRecords
$AWS sns list-topics
```

## Running the backend without Docker

```bash
cd backend
cp .env.example .env          # already points at http://localhost:4566
pip install -r requirements.txt
pip install Pillow pytesseract  # plus: apt install tesseract-ocr
python app.py
```

LocalStack must already be up, and `localstack/init.py` must have run, or
the tables will not exist. Set `MOCK_AWS=1` in `.env` to skip LocalStack
entirely and use in-memory stubs — and add `MOCK_PERSIST_FILE` (see
"Storage & persistence" above) if you want that data to survive restarts.
