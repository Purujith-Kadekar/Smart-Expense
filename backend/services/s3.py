"""
S3 helpers — presigned URL generation for direct-to-S3 receipt uploads.

The endpoint split
------------------
This is the bug that breaks every LocalStack upload flow, so it is worth
being explicit about.

The backend talks to LocalStack over the compose network at
`http://localstack:4566`. But a presigned URL is *handed to the browser*,
and the browser has no DNS entry for `localstack` — the PUT fails with
ERR_NAME_NOT_RESOLVED before it ever reaches LocalStack.

So we keep two endpoints:

  AWS_ENDPOINT_URL         http://localstack:4566   backend -> LocalStack
  AWS_PUBLIC_ENDPOINT_URL  http://localhost:4566    browser -> LocalStack

and sign with the *public* one. The signature covers the Host header, so
you cannot sign against one host and send to another — rewriting the
hostname after signing produces SignatureDoesNotMatch. A separate signing
client is the fix.

We also force path-style addressing. The default virtual-host style would
produce `http://receipts-bucket.localhost:4566/...`, which does not resolve
either.
"""

import os

from services.mock_aws import get_s3_client, get_presigning_s3_client

_BUCKET = os.environ.get("S3_BUCKET", "receipts-bucket")

# Client used for ordinary API calls (head_object, download, etc.) — points
# at the in-cluster endpoint.
_s3 = get_s3_client()

# Client used only to sign URLs the browser will call — points at the
# host-reachable endpoint.
_s3_presign = get_presigning_s3_client()


def generate_presigned_upload(s3_key, content_type=None, expires_in=300):
    """Return a presigned S3 PUT URL valid for `expires_in` seconds.

    The frontend PUTs the raw image bytes to this URL. Five minutes is
    ample for a phone photo on any wifi.

    `content_type` is deliberately NOT included in the signed parameters.
    If it were, the browser would have to send back a byte-identical
    Content-Type header or the signature check fails — and browsers
    normalise that header in ways that are hard to predict. Leaving it
    unsigned means any Content-Type the browser picks is accepted.
    """
    return _s3_presign.generate_presigned_url(
        "put_object",
        Params={"Bucket": _BUCKET, "Key": s3_key},
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )


def generate_presigned_download(s3_key, expires_in=900):
    """Return a presigned GET URL so the dashboard can display a receipt.

    The bucket is private, so a plain object URL would 403. Fifteen minutes
    covers a dashboard session without leaving long-lived links around.
    """
    return _s3_presign.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": s3_key},
        ExpiresIn=expires_in,
        HttpMethod="GET",
    )


def object_exists(s3_key):
    """True if the object is present in the bucket.

    Used by POST /api/expenses/trigger-ocr to fail fast with a clear error
    when the browser's PUT silently did not land, rather than letting the
    Lambda return an opaque s3_download_failed.
    """
    try:
        _s3.head_object(Bucket=_BUCKET, Key=s3_key)
        return True
    except Exception:
        return False
