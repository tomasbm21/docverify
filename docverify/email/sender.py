"""Email sender via Resend API.

Requires RESEND_API_KEY env var. Uses the Resend Python SDK.
Supports plain text, HTML, and file attachments (docx/xlsx as base64).

Usage:
    from docverify.email.sender import send_email, send_with_attachment

    send_email("to@example.com", "Subject", "<p>Hello</p>")
    send_with_attachment("to@example.com", "Subject", "See attached.", "/path/to/file.docx")
"""

import base64
import os
from pathlib import Path

from docverify.utils import get_logger

logger = get_logger(__name__)


def _get_api_key() -> str:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "RESEND_API_KEY not set. "
            "Get one at https://resend.com/api-keys"
        )
    return key


def _get_from() -> str:
    return os.environ.get("EMAIL_FROM", "onboarding@resend.dev")


def send_email(
    to: str,
    subject: str,
    html: str | None = None,
    text: str | None = None,
    from_addr: str | None = None,
) -> dict:
    """Send an email via Resend API.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        html: HTML body (optional).
        text: Plain text body (optional — used as fallback).
        from_addr: Sender address (defaults to EMAIL_FROM env var).

    Returns:
        Resend API response dict with 'id' key on success.

    Raises:
        ValueError: If RESEND_API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    import resend

    resend.api_key = _get_api_key()

    params: dict = {
        "from": from_addr or _get_from(),
        "to": [to],
        "subject": subject,
    }
    if html:
        params["html"] = html
    if text:
        params["text"] = text
    if not html and not text:
        params["text"] = ""  # Resend requires at least one body

    logger.debug("Sending email to %s: %s", to, subject)

    try:
        result = resend.Emails.send(params)
        logger.info("Email sent to %s — id: %s", to, result.get("id", "unknown"))
        return result
    except Exception as e:
        raise RuntimeError(f"Resend API error: {e}")


def send_with_attachment(
    to: str,
    subject: str,
    body: str,
    file_path: str,
    html: bool = False,
    from_addr: str | None = None,
) -> dict:
    """Send an email with a file attachment.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body (plain text or HTML if html=True).
        file_path: Path to the file to attach (.docx, .xlsx, etc.).
        html: If True, treat body as HTML.
        from_addr: Sender address (defaults to EMAIL_FROM env var).

    Returns:
        Resend API response dict.
    """
    import resend

    resend.api_key = _get_api_key()

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Attachment not found: {file_path}")

    # Read and base64-encode the file
    with open(path, "rb") as f:
        content_bytes = f.read()
    content_b64 = base64.b64encode(content_bytes).decode("ascii")

    params: dict = {
        "from": from_addr or _get_from(),
        "to": [to],
        "subject": subject,
        "attachments": [
            {
                "filename": path.name,
                "content": content_b64,
            }
        ],
    }
    if html:
        params["html"] = body
    else:
        params["text"] = body

    logger.debug("Sending email with attachment %s to %s", path.name, to)

    try:
        result = resend.Emails.send(params)
        logger.info("Email with attachment %s sent to %s — id: %s",
                     path.name, to, result.get("id", "unknown"))
        return result
    except Exception as e:
        raise RuntimeError(f"Resend API error: {e}")


def send_with_multiple_attachments(
    to: str,
    subject: str,
    body: str,
    file_paths: list[str],
    html: bool = False,
    from_addr: str | None = None,
) -> dict:
    """Send an email with multiple file attachments.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body.
        file_paths: List of paths to attach.
        html: If True, treat body as HTML.
        from_addr: Sender address.

    Returns:
        Resend API response dict.
    """
    import resend

    resend.api_key = _get_api_key()

    attachments = []
    for fp in file_paths:
        path = Path(fp)
        if not path.exists():
            logger.warning("Attachment not found, skipping: %s", fp)
            continue
        with open(path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("ascii")
        attachments.append({"filename": path.name, "content": content_b64})

    if not attachments:
        raise ValueError("No valid attachments found")

    params: dict = {
        "from": from_addr or _get_from(),
        "to": [to],
        "subject": subject,
        "attachments": attachments,
    }
    if html:
        params["html"] = body
    else:
        params["text"] = body

    logger.debug("Sending email with %d attachments to %s", len(attachments), to)

    try:
        result = resend.Emails.send(params)
        logger.info("Email with %d attachments sent to %s — id: %s",
                     len(attachments), to, result.get("id", "unknown"))
        return result
    except Exception as e:
        raise RuntimeError(f"Resend API error: {e}")


if __name__ == "__main__":
    print("docverify.email.sender — ready")
    print(f"  FROM: {_get_from()}")
    print(f"  API key: {'set' if os.environ.get('RESEND_API_KEY') else 'NOT SET'}")
