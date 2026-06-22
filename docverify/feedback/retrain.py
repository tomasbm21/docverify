"""Feedback retrain — exports corrected data as fine-tuning examples.

For each rejected/corrected finding, creates a labeled example suitable
for fine-tuning an LLM (Ollama, OpenAI, or similar). The goal is to
teach the model to correctly map field labels it previously got wrong.

Usage:
    from docverify.feedback.retrain import export_finetune_dataset

    count = export_finetune_dataset("data/feedback/finetune_dataset.jsonl")
    print(f"Exported {count} fine-tuning examples")
"""

import json
import os
from pathlib import Path

from docverify.feedback.tracker import FeedbackTracker
from docverify.utils import get_logger

logger = get_logger(__name__)

DEFAULT_OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "feedback", "finetune_dataset.jsonl"
)

# System prompt for the fine-tuning task
SYSTEM_PROMPT = (
    "You are a field-label mapper for shipping documents. "
    "Given a raw field label and a document snippet, "
    "map the label to one of these canonical fields: "
    "order_no, bl_no, reference, container_no, seal_no, "
    "shipper, consignee, vessel, voyage, pol, pod, ship_date, "
    "description, lot, cartons, net_kg, gross_kg, unit_price, units, "
    "amount, value, currency, invoice_no, invoice_date, buyer, incoterm. "
    "Respond with ONLY a JSON object."
)


def _build_example(record, canonical_docs: list[dict] | None = None) -> dict | None:
    """Build a fine-tuning example from a feedback record.

    Returns:
        Dict in OpenAI-style fine-tuning format, or None if not applicable.
    """
    if record.verdict not in ("rejected", "corrected"):
        return None

    # Extract the raw label from the field name
    # e.g. "identifiers.order_no" -> we need the original raw label
    field_parts = record.field.split(".")
    canonical_field = field_parts[-1] if field_parts else record.field

    # Build a minimal example
    user_msg = f"Map this shipping document label to a canonical field: '{canonical_field}'"
    if record.doc_type:
        user_msg += f"\nDocument type: {record.doc_type}"
    if record.notes:
        user_msg += f"\nContext: {record.notes}"

    # The correct answer based on human feedback
    assistant_msg = json.dumps({canonical_field: canonical_field})

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ],
        "metadata": {
            "shipment_id": record.shipment_id,
            "field": record.field,
            "verdict": record.verdict,
            "timestamp": record.timestamp,
        },
    }


def export_finetune_dataset(
    output_path: str | None = None,
    tracker: FeedbackTracker | None = None,
) -> int:
    """Export feedback as fine-tuning dataset.

    Args:
        output_path: Path to write the JSONL dataset.
        tracker: FeedbackTracker instance.

    Returns:
        Number of examples exported.
    """
    output_path = Path(output_path or DEFAULT_OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tracker = tracker or FeedbackTracker()

    records = tracker.read_all()
    if not records:
        logger.info("No feedback records — nothing to export")
        return 0

    examples = []
    for record in records:
        example = _build_example(record)
        if example:
            examples.append(example)

    if not examples:
        logger.info("No rejected/corrected records — nothing to export")
        return 0

    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    logger.info("Exported %d fine-tuning examples to %s", len(examples), output_path)
    return len(examples)


def export_for_ollama(
    output_path: str | None = None,
    tracker: FeedbackTracker | None = None,
) -> int:
    """Export in Ollama-compatible Modelfile format.

    Creates a Modelfile that fine-tunes the base model with feedback data.
    """
    tracker = tracker or FeedbackTracker()
    records = tracker.read_all()

    rejected = [r for r in records if r.verdict in ("rejected", "corrected")]
    if not rejected:
        logger.info("No rejected/corrected records — nothing to export")
        return 0

    # Build a simple training prompt/response file
    output_path = Path(output_path or DEFAULT_OUTPUT_PATH.replace(".jsonl", "_ollama.txt"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for r in rejected:
        field = r.field.split(".")[-1] if "." in r.field else r.field
        lines.append(f"INPUT: Map label '{field}' for {r.doc_type or 'shipping document'}")
        lines.append(f"OUTPUT: {json.dumps({field: field})}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("Exported %d Ollama training examples to %s", len(rejected), output_path)
    return len(rejected)


if __name__ == "__main__":
    count = export_finetune_dataset()
    print(f"Exported {count} fine-tuning examples")
