"""Tests for email sender and inbox modules."""

import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestEmailSender:
    """Test the Resend email sender."""

    def test_send_email_missing_api_key(self):
        """Raises ValueError if RESEND_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RESEND_API_KEY", None)
            from docverify.email.sender import send_email
            with pytest.raises(ValueError, match="RESEND_API_KEY"):
                send_email("test@example.com", "Subject", text="Body")

    def test_send_email_success(self):
        """send_email calls Resend API correctly."""
        mock_result = {"id": "msg_123"}

        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test123"}):
            with patch("resend.Emails.send", return_value=mock_result) as mock_send:
                from docverify.email.sender import send_email
                result = send_email("to@test.com", "Test Subject", html="<p>Hello</p>")

                assert result == {"id": "msg_123"}
                mock_send.assert_called_once()
                call_args = mock_send.call_args[0][0]
                assert call_args["to"] == ["to@test.com"]
                assert call_args["subject"] == "Test Subject"
                assert call_args["html"] == "<p>Hello</p>"

    def test_send_with_attachment(self):
        """send_with_attachment encodes file as base64."""
        mock_result = {"id": "msg_456"}

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"fake docx content")
            temp_path = f.name

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test123"}):
                with patch("resend.Emails.send", return_value=mock_result) as mock_send:
                    from docverify.email.sender import send_with_attachment
                    result = send_with_attachment(
                        "to@test.com", "Subject", "Body", temp_path
                    )

                    assert result == {"id": "msg_456"}
                    call_args = mock_send.call_args[0][0]
                    assert len(call_args["attachments"]) == 1
                    assert call_args["attachments"][0]["filename"].endswith(".docx")
                    # Verify base64 encoding
                    decoded = base64.b64decode(call_args["attachments"][0]["content"])
                    assert decoded == b"fake docx content"
        finally:
            os.unlink(temp_path)

    def test_send_with_attachment_missing_file(self):
        """Raises FileNotFoundError if attachment doesn't exist."""
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test123"}):
            from docverify.email.sender import send_with_attachment
            with pytest.raises(FileNotFoundError):
                send_with_attachment("to@test.com", "Sub", "Body", "/nonexistent/file.docx")


class TestEmailInbox:
    """Test the IMAP inbox module."""

    def test_poll_inbox_missing_credentials(self):
        """Raises ValueError if IMAP credentials are missing."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EMAIL_USER", None)
            os.environ.pop("EMAIL_PASSWORD", None)
            from docverify.email.inbox import poll_inbox
            with pytest.raises(ValueError, match="EMAIL_USER"):
                poll_inbox()

    def test_extract_attachments(self):
        """_extract_attachments correctly extracts .docx/.xlsx files."""
        from docverify.email.inbox import _extract_attachments

        # Create a mock attachment part
        att_part = MagicMock()
        att_part.get.side_effect = lambda key, default="": {
            "Content-Disposition": 'attachment; filename="invoice.docx"',
        }.get(key, default)
        att_part.get_filename.return_value = "invoice.docx"
        att_part.get_payload.return_value = b"fake docx bytes"

        # Create a mock non-attachment part
        body_part = MagicMock()
        body_part.get.return_value = ""
        body_part.get_filename.return_value = None

        msg = MagicMock()
        msg.walk.return_value = [att_part, body_part]

        with tempfile.TemporaryDirectory() as tmpdir:
            saved = _extract_attachments(msg, tmpdir)
            assert len(saved) == 1
            assert saved[0].endswith("invoice.docx")

            # Verify file was written
            assert Path(saved[0]).exists()
            assert Path(saved[0]).read_bytes() == b"fake docx bytes"

    def test_extract_attachments_skips_non_docs(self):
        """_extract_attachments skips non-document files."""
        from docverify.email.inbox import _extract_attachments

        att_part = MagicMock()
        att_part.get.side_effect = lambda key, default="": {
            "Content-Disposition": 'attachment; filename="report.csv"',
        }.get(key, default)
        att_part.get_filename.return_value = "report.csv"

        msg = MagicMock()
        msg.walk.return_value = [att_part]

        with tempfile.TemporaryDirectory() as tmpdir:
            saved = _extract_attachments(msg, tmpdir)
            assert len(saved) == 0


class TestAgentPersonas:
    """Test agent persona definitions."""

    def test_personas_exist(self):
        """Default persona roster has at least 3 entries."""
        from docverify.agents.personas import PERSONAS
        assert len(PERSONAS) >= 3

    def test_persona_email_body(self):
        """Persona generates a non-empty email body."""
        from docverify.agents.personas import PERSONAS
        persona = PERSONAS[0]
        body = persona.email_body(["doc1.docx"], {"order_no": "ORD-2026-12345"})
        assert "ORD-2026-12345" in body
        assert "doc1.docx" in body

    def test_persona_email_subject(self):
        """Persona generates a subject with order number."""
        from docverify.agents.personas import PERSONAS
        persona = PERSONAS[0]
        subject = persona.email_subject({"order_no": "ORD-2026-99999"})
        assert "ORD-2026-99999" in subject

    def test_get_persona_by_name(self):
        """get_persona finds existing persona."""
        from docverify.agents.personas import get_persona, PERSONAS
        result = get_persona(PERSONAS[0].name)
        assert result is not None
        assert result.name == PERSONAS[0].name

    def test_get_persona_not_found(self):
        """get_persona returns None for unknown name."""
        from docverify.agents.personas import get_persona
        assert get_persona("Nonexistent Person") is None


class TestAgentGenerator:
    """Test document generator."""

    def test_generate_shipment_data(self):
        """Generator produces valid shipment data."""
        from docverify.agents.generator import generate_shipment_data
        data = generate_shipment_data(rng_seed=42)

        assert data["order_no"].startswith("ORD-")
        assert data["bl_no"]  # not empty
        assert data["container_no"]  # not empty
        assert len(data["items"]) >= 2
        assert data["totals"]["cartons"] > 0
        assert data["totals"]["net_kg"] > 0

    def test_generate_deterministic(self):
        """Same seed produces same data."""
        from docverify.agents.generator import generate_shipment_data
        d1 = generate_shipment_data(rng_seed=123)
        d2 = generate_shipment_data(rng_seed=123)
        assert d1["order_no"] == d2["order_no"]
        assert d1["items"][0]["net_kg"] == d2["items"][0]["net_kg"]

    def test_generate_shipment_set(self):
        """generate_shipment_set creates .docx and .xlsx files."""
        from docverify.agents.generator import generate_shipment_set

        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_shipment_set(tmpdir, rng_seed=42)
            assert len(result["files"]) == 3  # BL + packing list + invoice
            for f in result["files"]:
                assert Path(f).exists()


class TestFeedbackTracker:
    """Test the feedback tracker."""

    def test_log_and_read(self):
        """Tracker logs records and reads them back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test_log.jsonl")
            from docverify.feedback.tracker import FeedbackTracker

            tracker = FeedbackTracker(log_path=log_path)
            tracker.log("G01", "identifiers.order_no", "confirmed", "Looks right")
            tracker.log("G02", "totals.net_kg", "rejected", "Weight wrong")

            records = tracker.read_all()
            assert len(records) == 2
            assert records[0].shipment_id == "G01"
            assert records[0].verdict == "confirmed"
            assert records[1].verdict == "rejected"

    def test_invalid_verdict_raises(self):
        """Invalid verdict raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from docverify.feedback.tracker import FeedbackTracker
            tracker = FeedbackTracker(log_path=os.path.join(tmpdir, "log.jsonl"))
            with pytest.raises(ValueError, match="Invalid verdict"):
                tracker.log("G01", "field", "invalid_verdict")

    def test_compute_metrics_empty(self):
        """Empty log returns zero metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from docverify.feedback.tracker import FeedbackTracker
            tracker = FeedbackTracker(log_path=os.path.join(tmpdir, "log.jsonl"))
            metrics = tracker.compute_metrics()
            assert metrics.total_reviews == 0
            assert metrics.accuracy == 0.0

    def test_compute_metrics_with_data(self):
        """Metrics correctly compute accuracy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "log.jsonl")
            from docverify.feedback.tracker import FeedbackTracker

            tracker = FeedbackTracker(log_path=log_path)
            # 3 confirmed, 1 rejected -> 75% accuracy
            tracker.log("G01", "f1", "confirmed")
            tracker.log("G01", "f2", "confirmed")
            tracker.log("G02", "f1", "confirmed")
            tracker.log("G02", "f2", "rejected")

            metrics = tracker.compute_metrics()
            assert metrics.total_reviews == 4
            assert metrics.confirmed == 3
            assert metrics.rejected == 1
            assert metrics.accuracy == 0.75
