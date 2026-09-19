# Smart Campus Expense & Invoice Verifier

A local-first campus expense tracker. Upload a receipt photo, OCR reads the
vendor / amount / date, the record lands in DynamoDB, and anything flagged
(over budget or a suspected duplicate) publishes an SNS alert.

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

## Layout

```
backend/            Flask API — auth, uploads, expenses, budgets
  services/         boto3 clients, DynamoDB + S3 + SES helpers
  routes/           blueprints, all mounted under /api
lambda/             ingestion handler, OCR engine, receipt text parser
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
| POST | `/api/expenses/trigger-ocr` | run the ingestion handler for an `s3_key` |
| GET | `/api/expenses` | the caller's receipts |
| GET | `/api/expenses/<id>` | one receipt, ownership-checked |
| POST | `/api/expenses/email` | email selected receipts as a bill via SES |
| GET | `/api/budget?month=YYYY-MM` | limit, income, total spent, savings |
| POST | `/api/budget` | upsert a monthly budget |
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
entirely and use in-memory stubs.
