"""
POST /api/upload-url
POST /api/expenses/trigger-ocr

POST /api/upload-url
    Issues a presigned S3 PUT URL so the frontend can upload the receipt
    photo directly to S3, bypassing Flask. The S3 key carries user_id and
    category so the Lambda can attribute the receipt to the right user.
    Format: receipts/{user_id}/{category}/{uuid}_{filename}

POST /api/expenses/trigger-ocr
    In docker-compose mode (LocalStack S3 + no real Lambda trigger),
    the frontend calls this AFTER the S3 PUT completes. The backend
    invokes the Lambda handler directly with a synthetic S3 event for
    the given s3_key. This sidesteps the flaky S3→Lambda notification
    in LocalStack Community Edition while still exercising the real
    OCR → DynamoDB pipeline.

    In real AWS, this endpoint is a no-op — S3 triggers Lambda
    automatically. The frontend always calls it; the backend decides
    whether to actually do anything based on whether MOCK_AWS / docker-
    compose mode is active.

Protected by `@require_auth`.
"""

import os
import sys
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from services.auth import require_auth
from services.mock_aws import is_mock_mode
from services.s3 import generate_presigned_upload, object_exists

upload_bp = Blueprint("upload", __name__)

VALID_CATEGORIES = {"college", "mess", "event", "other"}


def _import_lambda_function():
    """Import lambda/lambda_function.py, wherever it lives.

    In docker-compose the Dockerfile puts the lambda package at /lambda and
    adds it to PYTHONPATH, so a plain import works. When the backend runs
    from the repo on the host (`python app.py`) nothing puts lambda/ on
    sys.path — this function resolves it relative to this file:
    routes/ -> backend/ -> project root -> lambda/.

    The previous version hard-coded sys.path.insert(0, "/lambda"), which
    only exists inside the container — on the host every trigger-ocr call
    died with "No module named lambda_function" (HTTP 500), so receipts
    were uploaded to S3 but never turned into expense records.
    """
    try:
        import lambda_function  # noqa: F401  (already importable — Docker case)
        return lambda_function
    except ImportError:
        pass

    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    lambda_dir = os.path.join(root, "lambda")
    if lambda_dir not in sys.path:
        sys.path.insert(0, lambda_dir)
    import lambda_function
    return lambda_function


@upload_bp.post("/upload-url")
@require_auth
def create_upload_url():
    body = request.get_json(silent=True) or {}
    filename = body.get("filename")
    category = (body.get("category") or "").strip().lower()

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if category not in VALID_CATEGORIES:
        return jsonify({
            "error": "invalid_category",
            "valid_categories": sorted(VALID_CATEGORIES),
        }), 400

    user_id = request.user_id
    s3_key = f"receipts/{user_id}/{category}/{uuid.uuid4()}_{filename}"

    try:
        upload_url = generate_presigned_upload(s3_key)
    except Exception as exc:
        return jsonify({"error": "presign_failed", "detail": str(exc)}), 500

    return jsonify({"upload_url": upload_url, "s3_key": s3_key})


@upload_bp.post("/expenses/trigger-ocr")
@require_auth
def trigger_ocr():
    """Invoke the Lambda handler directly for a given S3 key.

    The frontend calls this AFTER the S3 PUT completes. In docker-compose
    mode (LocalStack S3, no real Lambda trigger), the backend invokes the
    Lambda handler directly with a synthetic S3 event. In real AWS, this
    is a no-op (S3 triggers Lambda automatically) but the call is harmless.

    Request: { "s3_key": "receipts/..." }
    Response: { "triggered": true, "expense_id": "...", "vendor": "...", ... }
               OR { "triggered": false, "reason": "real AWS — S3 triggers Lambda automatically" }
    """
    body = request.get_json(silent=True) or {}
    s3_key = body.get("s3_key")

    if not s3_key:
        return jsonify({"error": "s3_key is required"}), 400

    # Security: verify the s3_key belongs to the caller. The key format is
    # receipts/{user_id}/{category}/... — extract user_id and compare.
    parts = s3_key.split("/")
    if len(parts) < 4 or parts[0] != "receipts" or parts[1] != request.user_id:
        return jsonify({"error": "s3_key_does_not_belong_to_caller"}), 403

    # Ingestion ALWAYS runs in-process in this project — there is no deployed
    # S3→Lambda trigger anywhere (docker-compose invokes the handler directly
    # because LocalStack Community's S3 notifications are unreliable, and in
    # real-AWS mode the same in-process call writes to real DynamoDB/S3 via
    # boto3). This used to return 503 aws_endpoint_url_not_set when
    # AWS_ENDPOINT_URL was unset, which silently made real-DynamoDB mode
    # unusable: uploads stored fine but no expense record ever appeared.
    if not is_mock_mode() and not os.environ.get("AWS_ENDPOINT_URL"):
        print("[upload] AWS_ENDPOINT_URL unset — ingesting in-process against real AWS")

    bucket = os.environ.get("S3_BUCKET", "receipts-bucket")

    # Fail fast with a readable error if the browser's PUT never landed.
    # Without this the Lambda returns an opaque s3_download_failed and the
    # user has no idea whether the problem was the upload or the OCR.
    if not is_mock_mode() and not object_exists(s3_key):
        return jsonify({
            "error": "object_not_found_in_s3",
            "s3_key": s3_key,
            "bucket": bucket,
            "hint": "The presigned PUT did not complete. Check the browser "
                    "network tab for the PUT to http://localhost:4566 — a "
                    "DNS or CORS failure there is the usual cause.",
        }), 404

    # Build a synthetic S3 event and invoke the Lambda handler directly.
    # _import_lambda_function() resolves the lambda package both inside
    # Docker (/lambda on PYTHONPATH) and on a host checkout — see its
    # docstring for why this used to be the #1 host-mode upload failure.
    try:
        lambda_function = _import_lambda_function()
        from services import mock_aws as _mock_aws

        # Point the Lambda's boto3 clients at the same mock/localstack
        # clients the backend uses, so the DynamoDB write lands in the
        # same store.
        lambda_function.dynamodb = _mock_aws.get_dynamo_resource()
        lambda_function.sns = _mock_aws.get_sns_client()
        lambda_function.s3 = _mock_aws.get_s3_client()

        # In mock mode, download_image_from_s3 would fail (the mock S3
        # client doesn't support download_file). Monkey-patch it to return
        # a fake path — the OCR function is also patched by tests, but in
        # real docker-compose mode the real pytesseract runs against the
        # downloaded file.
        if is_mock_mode():
            # Mock mode — no real image, OCR returns empty → record with
            # defaults. This path is for `python app.py` dev without Docker.
            lambda_function.download_image_from_s3 = lambda bucket, key: f"/tmp/mock_{key}"
            lambda_function.run_ocr = lambda image_path: ""

        event = {
            "Records": [{
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": s3_key},
                }
            }]
        }
        result = lambda_function.lambda_handler(event, None)
        result_body = result.get("body", "{}")
        import json
        try:
            expense = json.loads(result_body)
        except (json.JSONDecodeError, TypeError):
            expense = {"raw": result_body}

        return jsonify({
            "triggered": True,
            "expense": expense,
        })
    except Exception as exc:
        # Log the full traceback for debugging but return a clean JSON error.
        import traceback
        traceback.print_exc()
        return jsonify({"error": "ocr_trigger_failed", "detail": str(exc)}), 500
