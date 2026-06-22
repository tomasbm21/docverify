"""REST API endpoints for DocVerify web UI."""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from docverify.utils import get_logger

logger = get_logger(__name__)

# Project root (docverify/)
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = DATA_DIR / "out"
CORPUS_DIR = DATA_DIR / "corpus"
ENV_PATH = PROJECT_ROOT / ".env"
LOG_PATH = DATA_DIR / "feedback" / "feedback_log.jsonl"

# Pipeline state
_pipeline_state = {
    "status": "idle",  # idle | running | complete | error
    "started_at": None,
    "finished_at": None,
    "last_run": None,
    "error": None,
    "output": [],
}
_pipeline_lock = threading.Lock()


def _read_json(path: Path) -> dict | list | None:
    """Read a JSON file, return None if not found."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_env() -> dict:
    """Read current .env file as a dict."""
    env = {}
    if not ENV_PATH.exists():
        return env
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(updates: dict) -> None:
    """Update .env file with new values. Preserves comments and order."""
    lines = []
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Build map of existing keys to line indices
    key_indices = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            key_indices[key] = i

    # Update existing keys
    for key, value in updates.items():
        if key in key_indices:
            idx = key_indices[key]
            lines[idx] = f"{key}={value}\n"
        else:
            lines.append(f"{key}={value}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _run_pipeline_thread(mode: str, **kwargs):
    """Run pipeline in a background thread."""
    global _pipeline_state

    with _pipeline_lock:
        _pipeline_state["status"] = "running"
        _pipeline_state["started_at"] = datetime.now(timezone.utc).isoformat()
        _pipeline_state["error"] = None
        _pipeline_state["output"] = []

    try:
        cmd = [sys.executable, "-m", "docverify.pipeline", "--out", str(OUT_DIR)]

        if mode == "corpus":
            corpus = kwargs.get("corpus_dir", str(CORPUS_DIR))
            cmd.extend(["--corpus", corpus])
        elif mode == "email":
            cmd.append("--email-inbox")
        elif mode == "simulate":
            cmd.append("--simulate-agents")
            cmd.extend(["--num-emails", str(kwargs.get("num_emails", 5))])
            cmd.extend(["--sim-mode", kwargs.get("sim_mode", "existing")])
            if kwargs.get("dry_run"):
                cmd.append("--dry-run")

        if kwargs.get("use_llm"):
            cmd.append("--use-llm")
        if kwargs.get("numeric_tolerance") is not None:  # BUG-013: was truthy check, dropped 0.0
            cmd.extend(["--numeric-tolerance", str(kwargs["numeric_tolerance"])])

        logger.info("Running pipeline: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )

        with _pipeline_lock:
            _pipeline_state["output"] = result.stdout.split("\n")
            if result.returncode == 0:
                _pipeline_state["status"] = "complete"
            else:
                _pipeline_state["status"] = "error"
                _pipeline_state["error"] = result.stderr[-500:] if result.stderr else "Unknown error"
            _pipeline_state["finished_at"] = datetime.now(timezone.utc).isoformat()

    except subprocess.TimeoutExpired:
        with _pipeline_lock:
            _pipeline_state["status"] = "error"
            _pipeline_state["error"] = "Pipeline timed out (300s)"
            _pipeline_state["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        with _pipeline_lock:
            _pipeline_state["status"] = "error"
            _pipeline_state["error"] = str(e)
            _pipeline_state["finished_at"] = datetime.now(timezone.utc).isoformat()


# --- API Functions ---

def get_status() -> dict:
    """Get pipeline status and last run summary."""
    with _pipeline_lock:
        state = dict(_pipeline_state)

    # Add last run summary from results.json
    results = _read_json(OUT_DIR / "results.json")
    if results and "shipments" in results:
        shipments = results["shipments"]
        state["last_run"] = {
            "total_docs": results.get("total_docs", len(results.get("shipments", []))),
            "total_groups": len(shipments),
            "passed": sum(1 for s in shipments if s.get("verdict") == "PASS"),
            "failed": sum(1 for s in shipments if s.get("verdict") == "FAIL"),
            "timestamp": datetime.fromtimestamp(
                (OUT_DIR / "results.json").stat().st_mtime
            ).isoformat() if (OUT_DIR / "results.json").exists() else None,
        }

    return state


def get_inbox() -> list[dict]:
    """Get emails from IMAP inbox."""
    try:
        from docverify.email.inbox import poll_inbox
        env = _read_env()

        # Connect and fetch headers
        import email
        import imaplib

        host = env.get("EMAIL_HOST", "imap.gmail.com")
        user = env.get("EMAIL_USER", "")
        password = env.get("EMAIL_PASSWORD", "")

        if not user or not password:
            return [{"error": "EMAIL_USER and EMAIL_PASSWORD not configured"}]

        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select("INBOX")

        status, message_ids = mail.search(None, "ALL")
        if status != "OK":
            mail.logout()
            return []

        ids = message_ids[0].split()
        if not ids:
            mail.logout()
            return []

        # Get last 20 emails
        ids = ids[-20:]
        emails = []

        for msg_id in reversed(ids):
            try:
                status, msg_data = mail.fetch(msg_id, "(RFC822.HEADER)")
                if status != "OK":
                    continue

                raw_header = msg_data[0][1]
                msg = email.message_from_bytes(raw_header)

                from docverify.email.inbox import _decode_header_value

                # Count attachments
                att_count = 0
                for part in msg.walk():
                    disp = str(part.get("Content-Disposition", ""))
                    if "attachment" in disp:
                        filename = part.get_filename()
                        if filename:
                            ext = Path(_decode_header_value(filename)).suffix.lower()
                            if ext in (".docx", ".xlsx"):
                                att_count += 1

                emails.append({
                    "id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                    "from": _decode_header_value(msg.get("From", "")),
                    "subject": _decode_header_value(msg.get("Subject", "")),
                    "date": _decode_header_value(msg.get("Date", "")),
                    "attachments": att_count,
                    "read": "\\Seen" in str(msg.get("Flags", "")),
                })
            except Exception:
                continue

        mail.logout()
        return emails

    except Exception as e:
        logger.error("Failed to fetch inbox: %s", e)
        return [{"error": str(e)}]


def get_results() -> dict | None:
    """Get pipeline results."""
    return _read_json(OUT_DIR / "results.json")


def get_group_detail(group_id: str) -> dict | None:
    """Get detail for a specific shipment group."""
    results = _read_json(OUT_DIR / "results.json")
    if not results or "shipments" not in results:
        return None

    for shipment in results["shipments"]:
        if shipment.get("group_id") == group_id:
            return shipment
    return None


def get_scorecard() -> dict | None:
    """Get scoring results."""
    return _read_json(OUT_DIR / "scorecard.json")


def get_feedback_metrics() -> dict:
    """Get feedback metrics."""
    try:
        from docverify.feedback.tracker import FeedbackTracker
        tracker = FeedbackTracker(log_path=str(LOG_PATH))
        metrics = tracker.compute_metrics()
        return metrics.model_dump(mode="json")
    except Exception:
        return {"total_reviews": 0, "accuracy": 0.0}


def get_feedback_log() -> list[dict]:
    """Get raw feedback records."""
    try:
        from docverify.feedback.tracker import FeedbackTracker
        tracker = FeedbackTracker(log_path=str(LOG_PATH))
        records = tracker.read_all()
        return [r.model_dump(mode="json") for r in records[-50:]]  # last 50
    except Exception:
        return []


def log_feedback(shipment_id: str, field: str, verdict: str, notes: str = "") -> dict:
    """Submit a feedback entry."""
    try:
        from docverify.feedback.tracker import FeedbackTracker
        tracker = FeedbackTracker(log_path=str(LOG_PATH))
        record = tracker.log(shipment_id, field, verdict, notes)
        return {"success": True, "record": record.model_dump(mode="json")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_config() -> dict:
    """Get current configuration."""
    env = _read_env()

    # Mask sensitive values
    masked = {}
    sensitive_keys = {"RESEND_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "EMAIL_PASSWORD"}
    for key, value in env.items():
        if key in sensitive_keys and value:
            masked[key] = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
        else:
            masked[key] = value

    return masked


_ALLOWED_CONFIG_KEYS = {
    "LLM_PROVIDER", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
    "EMAIL_FROM", "EMAIL_TO", "EMAIL_HOST", "EMAIL_USER", "EMAIL_PASSWORD",
    "RESEND_API_KEY",
    "NUMERIC_TOLERANCE",
}


def update_config(updates: dict) -> dict:
    """Update configuration values. Writes to .env AND updates running process."""
    # BUG-033: Reject unknown keys
    unknown = set(updates.keys()) - _ALLOWED_CONFIG_KEYS
    if unknown:
        return {"success": False, "error": f"Unknown config keys: {', '.join(sorted(unknown))}"}
    try:
        _write_env(updates)
        # Push changes into the running process so they take effect immediately
        os.environ.update(updates)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_ollama_health() -> dict:
    """Check Ollama connectivity."""
    try:
        from docverify.llm.ollama_client import health_check, _get_config
        base_url, model = _get_config()
        healthy = health_check()
        return {
            "healthy": healthy,
            "url": base_url,
            "model": model,
        }
    except Exception as e:
        return {"healthy": False, "error": str(e)}


def get_logs(lines: int = 100) -> list[str]:
    """Get recent log output from the pipeline."""
    with _pipeline_lock:
        return _pipeline_state.get("output", [])[-lines:]


def trigger_pipeline(mode: str, **kwargs) -> dict:
    """Start a pipeline run in the background."""
    # BUG-033: Validate numeric_tolerance if provided
    tol = kwargs.get("numeric_tolerance")
    if tol is not None:
        try:
            tol = float(tol)
            import math
            if math.isnan(tol) or math.isinf(tol) or tol < 0:
                return {"success": False, "error": "numeric_tolerance must be a non-negative finite number"}
            kwargs["numeric_tolerance"] = tol
        except (ValueError, TypeError):
            return {"success": False, "error": "numeric_tolerance must be a number"}

    # BUG-033: Validate num_emails if provided
    num = kwargs.get("num_emails")
    if num is not None:
        try:
            num = int(num)
            if num < 1:
                return {"success": False, "error": "num_emails must be at least 1"}
            kwargs["num_emails"] = num
        except (ValueError, TypeError):
            return {"success": False, "error": "num_emails must be a positive integer"}

    with _pipeline_lock:
        if _pipeline_state["status"] == "running":
            return {"success": False, "error": "Pipeline already running"}

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(mode,),
        kwargs=kwargs,
        daemon=True,
    )
    thread.start()
    return {"success": True, "message": f"Pipeline started ({mode} mode)"}


# --- Document Viewer ---

def list_documents() -> list[dict]:
    """List all .docx/.xlsx files in the corpus directory."""
    docs = []
    if not CORPUS_DIR.is_dir():
        return docs

    for fpath in sorted(CORPUS_DIR.iterdir()):
        if fpath.suffix.lower() in (".docx", ".xlsx"):
            stat = fpath.stat()
            docs.append({
                "filename": fpath.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "type": fpath.suffix.lower().lstrip("."),
            })
    return docs


def get_document_content(filename: str) -> dict:
    """Parse a .docx or .xlsx file and return its text + tables."""
    filepath = (CORPUS_DIR / filename).resolve()
    # BUG-040: prevent path traversal
    if not filepath.is_relative_to(CORPUS_DIR.resolve()):
        return {"error": "Access denied"}
    if not filepath.exists():
        return {"error": "File not found"}
    if filepath.suffix.lower() not in (".docx", ".xlsx"):
        return {"error": "Unsupported file type"}

    try:
        from docverify.ingestion.ingest import ingest_file
        raw = ingest_file(str(filepath))
        return {
            "filename": filename,
            "type": raw.source_format.value,
            "text": raw.text,
            "tables": raw.tables,
            "doc_id": raw.doc_id,
        }
    except Exception as e:
        return {"error": str(e)}
