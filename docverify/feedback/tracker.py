"""Feedback tracker — logs human confirmations/rejections of findings.

Every time a human reviews a pipeline finding and confirms or rejects it,
a FeedbackRecord is appended to the feedback log. This log is the source
of truth for the tuner and retrain modules.

Usage:
    from docverify.feedback.tracker import FeedbackTracker

    tracker = FeedbackTracker()
    tracker.log("G01", "identifiers.order_no", "confirmed", "Order number mismatch confirmed")
    tracker.log("G02", "totals.net_kg", "rejected", "Weight was actually correct")
    metrics = tracker.compute_metrics()
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from docverify.utils import get_logger

logger = get_logger(__name__)

DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "feedback", "feedback_log.jsonl"
)


class FeedbackRecord(BaseModel):
    """A single human feedback entry."""
    timestamp: str
    shipment_id: str
    field: str                   # e.g. "identifiers.order_no", "totals.net_kg"
    verdict: str                 # "confirmed" | "rejected" | "corrected"
    notes: str = ""
    pipeline_verdict: str = ""   # what the pipeline originally said (PASS/FAIL)
    severity: str = ""           # finding severity (high/medium/low)
    provider: str = ""           # which LLM provider was used (if any)
    doc_type: str = ""           # document type where finding was


class FeedbackMetrics(BaseModel):
    """Computed metrics from the feedback log."""
    total_reviews: int = 0
    confirmed: int = 0
    rejected: int = 0
    corrected: int = 0
    accuracy: float = 0.0       # confirmed / total
    error_rate_by_field: dict[str, float] = Field(default_factory=dict)
    error_rate_by_doc_type: dict[str, float] = Field(default_factory=dict)
    trend: list[dict] = Field(default_factory=list)  # [{date, accuracy, count}]


class FeedbackTracker:
    """Append-only feedback log with metric computation."""

    def __init__(self, log_path: str | None = None):
        self.log_path = Path(log_path or DEFAULT_LOG_PATH)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        shipment_id: str,
        field: str,
        verdict: str,
        notes: str = "",
        pipeline_verdict: str = "",
        severity: str = "",
        provider: str = "",
        doc_type: str = "",
    ) -> FeedbackRecord:
        """Append a feedback record to the log.

        Args:
            shipment_id: Shipment group ID (e.g. "G01").
            field: The field that was reviewed (e.g. "identifiers.order_no").
            verdict: Human verdict — "confirmed", "rejected", or "corrected".
            notes: Optional human notes.
            pipeline_verdict: What the pipeline said (PASS/FAIL).
            severity: Finding severity.
            provider: LLM provider used.
            doc_type: Document type.

        Returns:
            The created FeedbackRecord.
        """
        if verdict not in ("confirmed", "rejected", "corrected"):
            raise ValueError(f"Invalid verdict: {verdict}. Use confirmed/rejected/corrected.")

        record = FeedbackRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            shipment_id=shipment_id,
            field=field,
            verdict=verdict,
            notes=notes,
            pipeline_verdict=pipeline_verdict,
            severity=severity,
            provider=provider,
            doc_type=doc_type,
        )

        # Append to JSONL
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

        logger.info("Feedback logged: %s/%s -> %s", shipment_id, field, verdict)
        return record

    def read_all(self) -> list[FeedbackRecord]:
        """Read all feedback records from the log."""
        if not self.log_path.exists():
            return []

        records = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(FeedbackRecord.model_validate_json(line))
                except Exception:
                    logger.warning("Skipping malformed feedback line")
        return records

    def compute_metrics(self, window_days: int = 30) -> FeedbackMetrics:
        """Compute accuracy and error rate metrics from the feedback log.

        Args:
            window_days: Only consider records from the last N days.

        Returns:
            FeedbackMetrics with aggregated stats.
        """
        records = self.read_all()
        if not records:
            return FeedbackMetrics()

        # Filter by window
        cutoff = datetime.now(timezone.utc).timestamp() - (window_days * 86400)
        recent = []
        for r in records:
            try:
                ts = datetime.fromisoformat(r.timestamp).timestamp()
                if ts >= cutoff:
                    recent.append(r)
            except Exception:
                recent.append(r)  # include if can't parse

        if not recent:
            return FeedbackMetrics()

        total = len(recent)
        confirmed = sum(1 for r in recent if r.verdict == "confirmed")
        rejected = sum(1 for r in recent if r.verdict == "rejected")
        corrected = sum(1 for r in recent if r.verdict == "corrected")

        # Error rate by field
        field_counts: dict[str, dict[str, int]] = {}
        for r in recent:
            if r.field not in field_counts:
                field_counts[r.field] = {"confirmed": 0, "rejected": 0, "corrected": 0}
            field_counts[r.field][r.verdict] = field_counts[r.field].get(r.verdict, 0) + 1

        error_rate_by_field = {}
        for field, counts in field_counts.items():
            field_total = sum(counts.values())
            if field_total > 0:
                error_rate_by_field[field] = round(
                    (counts.get("rejected", 0) + counts.get("corrected", 0)) / field_total, 3
                )

        # Error rate by doc type
        doc_counts: dict[str, dict[str, int]] = {}
        for r in recent:
            if r.doc_type:
                if r.doc_type not in doc_counts:
                    doc_counts[r.doc_type] = {"confirmed": 0, "rejected": 0, "corrected": 0}
                doc_counts[r.doc_type][r.verdict] = doc_counts[r.doc_type].get(r.verdict, 0) + 1

        error_rate_by_doc_type = {}
        for dt, counts in doc_counts.items():
            dt_total = sum(counts.values())
            if dt_total > 0:
                error_rate_by_doc_type[dt] = round(
                    (counts.get("rejected", 0) + counts.get("corrected", 0)) / dt_total, 3
                )

        # Trend (group by date)
        date_groups: dict[str, list[FeedbackRecord]] = {}
        for r in recent:
            date_key = r.timestamp[:10]  # YYYY-MM-DD
            date_groups.setdefault(date_key, []).append(r)

        trend = []
        for date_key in sorted(date_groups.keys()):
            group = date_groups[date_key]
            g_confirmed = sum(1 for r in group if r.verdict == "confirmed")
            g_total = len(group)
            trend.append({
                "date": date_key,
                "accuracy": round(g_confirmed / g_total, 3) if g_total > 0 else 0.0,
                "count": g_total,
            })

        return FeedbackMetrics(
            total_reviews=total,
            confirmed=confirmed,
            rejected=rejected,
            corrected=corrected,
            accuracy=round(confirmed / total, 3) if total > 0 else 0.0,
            error_rate_by_field=error_rate_by_field,
            error_rate_by_doc_type=error_rate_by_doc_type,
            trend=trend,
        )


if __name__ == "__main__":
    tracker = FeedbackTracker()
    records = tracker.read_all()
    print(f"Feedback log: {len(records)} records at {tracker.log_path}")
    if records:
        metrics = tracker.compute_metrics()
        print(f"  Accuracy: {metrics.accuracy:.1%}")
        print(f"  Confirmed: {metrics.confirmed}, Rejected: {metrics.rejected}, Corrected: {metrics.corrected}")
