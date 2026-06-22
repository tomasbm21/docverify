"""Email inbox via IMAP — polls for emails with .docx/.xlsx/.pdf attachments.

Uses stdlib imaplib + email modules — no extra dependencies.
Downloads attachments to a temp directory and returns RawDoc records
using the same ingest_file() function as the file-based pipeline.

Usage:
    from docverify.email.inbox import poll_inbox, fetch_unread_docs

    # One-shot: fetch all unread docs
    raw_docs = fetch_unread_docs()

    # With custom settings
    raw_docs = fetch_unread_docs(
        host="imap.gmail.com",
        user="you@gmail.com",
        password="app-password",
        mark_read=True,
    )
"""

import email
import imaplib
import os
import tempfile
from email.header import decode_header
from pathlib import Path

from docverify.utils import get_logger

logger = get_logger(__name__)

# Supported document extensions
DOC_EXTENSIONS = {".docx", ".xlsx", ".pdf"}


def _decode_header_value(value: str) -> str:
    """Decode an email header value (handles encoded words)."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_attachments(msg: email.message.Message, save_dir: str) -> list[str]:
    """Extract .docx/.xlsx attachments from an email message.

    Args:
        msg: The email message object.
        save_dir: Directory to save attachments to.

    Returns:
        List of file paths where attachments were saved.
    """
    saved = []

    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" not in content_disposition:
            continue

        filename = part.get_filename()
        if filename:
            filename = _decode_header_value(filename)
        if not filename:
            continue

        ext = Path(filename).suffix.lower()
        if ext not in DOC_EXTENSIONS:
            logger.debug("Skipping non-document attachment: %s", filename)
            continue

        # Save the attachment
        filepath = Path(save_dir) / filename
        with open(filepath, "wb") as f:
            f.write(part.get_payload(decode=True))

        saved.append(str(filepath))
        logger.debug("Saved attachment: %s", filepath)

    return saved


def poll_inbox(
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    folder: str = "INBOX",
    mark_read: bool = True,
    search_criteria: str = "UNSEEN",
    max_emails: int = 50,
) -> list[str]:
    """Poll IMAP inbox for emails with document attachments.

    Args:
        host: IMAP server (defaults to EMAIL_HOST env var).
        user: Email username (defaults to EMAIL_USER env var).
        password: Email password (defaults to EMAIL_PASSWORD env var).
        folder: IMAP folder to search (default: INBOX).
        mark_read: If True, mark processed emails as SEEN.
        search_criteria: IMAP search criteria (default: UNSEEN).
        max_emails: Maximum number of emails to process.

    Returns:
        List of file paths to downloaded attachments.
    """
    host = host or os.environ.get("EMAIL_HOST", "imap.gmail.com")
    user = user or os.environ.get("EMAIL_USER", "")
    password = password or os.environ.get("EMAIL_PASSWORD", "")

    if not user or not password:
        raise ValueError(
            "EMAIL_USER and EMAIL_PASSWORD must be set for IMAP access. "
            "For Gmail, use an App Password: https://myaccount.google.com/apppasswords"
        )

    logger.info("Polling %s@%s for unread emails with attachments...", user, host)

    # Create temp directory for attachments
    temp_dir = tempfile.mkdtemp(prefix="docverify_inbox_")
    all_attachments: list[str] = []

    try:
        # Connect
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select(folder)

        # Search
        status, message_ids = mail.search(None, search_criteria)
        if status != "OK":
            logger.warning("IMAP search failed: %s", status)
            return []

        ids = message_ids[0].split()
        if not ids:
            logger.info("No unread emails found")
            return []

        # Limit
        ids = ids[-max_emails:]
        logger.info("Found %d unread email(s), processing up to %d", len(ids), max_emails)

        for msg_id in ids:
            try:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_value(msg.get("Subject", ""))
                from_addr = _decode_header_value(msg.get("From", ""))
                logger.debug("Processing email from %s: %s", from_addr, subject)

                # Extract attachments
                attachments = _extract_attachments(msg, temp_dir)
                if attachments:
                    all_attachments.extend(attachments)
                    logger.info("  -> %d document attachment(s) from: %s",
                               len(attachments), from_addr)

                # Mark as read
                if mark_read:
                    mail.store(msg_id, "+FLAGS", "\\Seen")

            except Exception:
                logger.warning("Failed to process email %s", msg_id, exc_info=True)

        mail.logout()

    except imaplib.IMAP4.error as e:
        raise ConnectionError(f"IMAP connection failed: {e}")
    except Exception:
        logger.error("IMAP polling failed", exc_info=True)
        raise

    logger.info("Downloaded %d document attachment(s) to %s", len(all_attachments), temp_dir)
    return all_attachments


def fetch_unread_docs(
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    folder: str = "INBOX",
    mark_read: bool = True,
    max_emails: int = 50,
) -> "list[RawDoc]":
    """Fetch unread emails with document attachments and convert to RawDoc records.

    This is the main integration point with the pipeline — returns the same
    RawDoc type as ingest_dir().

    Args:
        host: IMAP server (defaults to EMAIL_HOST env var).
        user: Email username (defaults to EMAIL_USER env var).
        password: Email password (defaults to EMAIL_PASSWORD env var).
        folder: IMAP folder to search.
        mark_read: If True, mark processed emails as SEEN.
        max_emails: Maximum number of emails to process.

    Returns:
        List of RawDoc records from the downloaded attachments.
    """
    from docverify.ingestion.ingest import ingest_file

    file_paths = poll_inbox(
        host=host,
        user=user,
        password=password,
        folder=folder,
        mark_read=mark_read,
        max_emails=max_emails,
    )

    raw_docs = []
    for fp in file_paths:
        try:
            raw_doc = ingest_file(fp)
            # Override source_path to indicate email origin
            raw_doc.source_path = f"email://{Path(fp).name}"
            raw_docs.append(raw_doc)
        except Exception:
            logger.warning("Failed to ingest email attachment: %s", fp, exc_info=True)

    return raw_docs


if __name__ == "__main__":
    print("docverify.email.inbox — ready")
    print(f"  Host: {os.environ.get('EMAIL_HOST', 'imap.gmail.com')}")
    print(f"  User: {os.environ.get('EMAIL_USER', 'NOT SET')}")
    print(f"  Password: {'set' if os.environ.get('EMAIL_PASSWORD') else 'NOT SET'}")
