"""SES client factory — follows the same is_mock_mode() pattern as
services/s3.py. In mock mode (no AWS credentials detected), returns the
in-memory _MockSESClient that captures sent emails in a list. In
production, returns a real boto3 SES client.

The email-sending route (POST /api/expenses/email) calls `send_email()`
on whatever this factory returns — it doesn't know or care which one.
"""

import os

from services.mock_aws import get_ses_client

# The "From" address for all outgoing emails. In production this MUST be
# a verified SES sender identity (domain or email address). Configure via
# the SES_VERIFIED_SENDER env var. In mock mode the value is captured but
# never used to actually send, so any string works.
SES_VERIFIED_SENDER = os.environ.get("SES_VERIFIED_SENDER", "noreply@outlay.local")

_ses = get_ses_client()


def send_expense_bill(recipient_email, subject, html_body, text_body=None):
    """Send an email via SES (or the mock). Returns the SES MessageId.

    `recipient_email` — single "To" address.
    `subject`         — email subject line.
    `html_body`       — HTML email body (required — the bill is rendered as
                        an HTML table).
    `text_body`       — optional plaintext fallback for mail clients that
                        don't render HTML. If omitted, SES will still
                        deliver but the user sees raw HTML.
    """
    message = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {
            "Html": {"Data": html_body, "Charset": "UTF-8"},
        },
    }
    if text_body:
        message["Body"]["Text"] = {"Data": text_body, "Charset": "UTF-8"}

    response = _ses.send_email(
        Source=SES_VERIFIED_SENDER,
        Destination={"ToAddresses": [recipient_email]},
        Message=message,
    )
    return response.get("MessageId")
