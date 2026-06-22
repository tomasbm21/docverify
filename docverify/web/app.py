"""DocVerify Web UI — FastAPI application.

Serves the REST API and static frontend files.

Usage:
    python -m docverify.web
    # or
    uvicorn docverify.web.app:app --host 0.0.0.0 --port 8080 --reload
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE anything else reads os.environ
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from docverify.web.api import (
    check_ollama_health,
    get_config,
    get_feedback_log,
    get_feedback_metrics,
    get_group_detail,
    get_inbox,
    get_logs,
    get_results,
    get_scorecard,
    get_status,
    log_feedback,
    trigger_pipeline,
    update_config,
    list_documents,
    get_document_content,
)

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="DocVerify",
    description="Shipping document verification engine — Web UI",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Routes ---

@app.get("/api/status")
def api_status():
    return get_status()


@app.post("/api/pipeline/run")
def api_pipeline_run(body: dict = None):
    body = body or {}
    return trigger_pipeline(
        "corpus",
        corpus_dir=body.get("corpus_dir"),
        use_llm=body.get("use_llm", False),
        numeric_tolerance=body.get("numeric_tolerance", 0.0),
    )


@app.post("/api/pipeline/email")
def api_pipeline_email(body: dict = None):
    body = body or {}
    return trigger_pipeline(
        "email",
        use_llm=body.get("use_llm", False),
        numeric_tolerance=body.get("numeric_tolerance", 0.0),
    )


@app.post("/api/simulate")
def api_simulate(body: dict = None):
    body = body or {}
    return trigger_pipeline(
        "simulate",
        num_emails=body.get("num_emails", 5),
        sim_mode=body.get("sim_mode", "existing"),
        dry_run=body.get("dry_run", False),
        use_llm=body.get("use_llm", False),
    )


@app.get("/api/inbox")
def api_inbox():
    return get_inbox()


@app.get("/api/results")
def api_results():
    return get_results()


@app.get("/api/results/{group_id}")
def api_group_detail(group_id: str):
    detail = get_group_detail(group_id)
    if detail is None:
        return {"error": "Group not found"}
    return detail


@app.get("/api/scorecard")
def api_scorecard():
    return get_scorecard()


@app.get("/api/feedback")
def api_feedback():
    return get_feedback_metrics()


@app.get("/api/feedback/log")
def api_feedback_log():
    return get_feedback_log()


@app.post("/api/feedback/log")
def api_feedback_submit(body: dict):
    return log_feedback(
        shipment_id=body.get("shipment_id", ""),
        field=body.get("field", ""),
        verdict=body.get("verdict", ""),
        notes=body.get("notes", ""),
    )


@app.get("/api/config")
def api_config():
    return get_config()


@app.post("/api/config")
def api_config_update(body: dict):
    return update_config(body)


@app.get("/api/health/ollama")
def api_health_ollama():
    return check_ollama_health()


@app.get("/api/logs")
def api_logs(lines: int = 100):
    return get_logs(lines)


@app.get("/api/documents")
def api_documents():
    """List all documents in the corpus."""
    return list_documents()


@app.get("/api/documents/{filename}")
def api_document_content(filename: str):
    """Get parsed content of a single document."""
    return get_document_content(filename)


@app.post("/api/email/test")
def api_email_test():
    """Send a test email via Resend."""
    from docverify.email.sender import send_email
    try:
        result = send_email(
            os.environ.get("EMAIL_TO", "tomasborja21@gmail.com"),
            "DocVerify Test Email",
            html="<h2>DocVerify</h2><p>If you see this, Resend is working! ✅</p>",
        )
        return {"success": True, "id": result.get("id", "unknown")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Static Files ---

@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files AFTER API routes
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main():
    parser = argparse.ArgumentParser(description="DocVerify Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(
        "docverify.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
