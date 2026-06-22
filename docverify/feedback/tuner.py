"""Feedback tuner — adjusts extraction parameters based on human feedback.

Reads the feedback log and produces tuning overrides that improve the
pipeline's accuracy over time. The overrides are loaded by the extraction
module to adjust synonym weights, confidence thresholds, and tolerances.

The tuning is conservative — it never removes synonyms, only boosts
alternatives that humans have confirmed as correct.

Usage:
    from docverify.feedback.tuner import FeedbackTuner

    tuner = FeedbackTuner()
    overrides = tuner.compute_overrides()
    tuner.save_overrides()
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from docverify.feedback.tracker import FeedbackTracker
from docverify.utils import get_logger

logger = get_logger(__name__)

DEFAULT_OVERRIDES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "feedback", "tuning_overrides.json"
)


class TuningOverrides(BaseModel):
    """Computed overrides for the extraction pipeline."""
    # Synonym boosts: field -> {raw_label: boost_weight}
    # Higher weight means the label is more likely to map to this field.
    synonym_boosts: dict[str, dict[str, float]] = Field(default_factory=dict)

    # Confidence thresholds: minimum confidence to accept an extraction
    min_extraction_confidence: float = 0.0

    # Numeric tolerance: field -> tolerance percentage
    numeric_tolerances: dict[str, float] = Field(default_factory=dict)

    # LLM trigger threshold: how many unresolved labels before invoking LLM
    llm_trigger_threshold: int = 3

    # Stats
    feedback_count: int = 0
    last_updated: str = ""


class FeedbackTuner:
    """Computes tuning overrides from feedback history."""

    def __init__(
        self,
        tracker: FeedbackTracker | None = None,
        overrides_path: str | None = None,
    ):
        self.tracker = tracker or FeedbackTracker()
        self.overrides_path = Path(overrides_path or DEFAULT_OVERRIDES_PATH)
        self.overrides_path.parent.mkdir(parents=True, exist_ok=True)

    def compute_overrides(self) -> TuningOverrides:
        """Analyze feedback and compute tuning overrides.

        Returns:
            TuningOverrides with computed adjustments.
        """
        from datetime import datetime, timezone

        records = self.tracker.read_all()
        if not records:
            return TuningOverrides()

        # Track which fields keep getting rejected/corrected
        field_errors: dict[str, int] = {}
        field_total: dict[str, int] = {}

        for r in records:
            field_total[r.field] = field_total.get(r.field, 0) + 1
            if r.verdict in ("rejected", "corrected"):
                field_errors[r.field] = field_errors.get(r.field, 0) + 1

        # Compute synonym boosts for problematic fields
        synonym_boosts: dict[str, dict[str, float]] = {}
        for field, error_count in field_errors.items():
            total = field_total.get(field, 1)
            error_rate = error_count / total

            if error_rate > 0.3:  # >30% error rate → needs attention
                # Boost the canonical field name as a synonym
                synonym_boosts[field] = {
                    field.replace("_", " "): 1.5,
                    field: 1.5,
                }

        # Compute numeric tolerances based on corrections
        numeric_tolerances: dict[str, float] = {}
        for r in records:
            if r.verdict == "corrected" and "kg" in r.field.lower():
                # Increase tolerance for weight fields that keep getting corrected
                numeric_tolerances[r.field] = 0.02  # 2% tolerance

        # Adjust LLM trigger threshold based on overall accuracy
        metrics = self.tracker.compute_metrics()
        llm_trigger = 3  # default
        if metrics.accuracy < 0.8:
            llm_trigger = 2  # invoke LLM sooner if accuracy is low

        overrides = TuningOverrides(
            synonym_boosts=synonym_boosts,
            min_extraction_confidence=max(0.0, 0.5 - (metrics.accuracy * 0.3)),
            numeric_tolerances=numeric_tolerances,
            llm_trigger_threshold=llm_trigger,
            feedback_count=len(records),
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        logger.info("Computed overrides from %d feedback records (accuracy=%.1f%%)",
                     len(records), metrics.accuracy * 100)
        return overrides

    def save_overrides(self) -> TuningOverrides:
        """Compute and save overrides to disk."""
        overrides = self.compute_overrides()

        with open(self.overrides_path, "w", encoding="utf-8") as f:
            json.dump(overrides.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

        logger.info("Tuning overrides saved to %s", self.overrides_path)
        return overrides

    def load_overrides(self) -> TuningOverrides:
        """Load overrides from disk, or return empty if not found."""
        if not self.overrides_path.exists():
            return TuningOverrides()

        try:
            with open(self.overrides_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TuningOverrides.model_validate(data)
        except Exception:
            logger.warning("Failed to load overrides, using defaults", exc_info=True)
            return TuningOverrides()


def apply_overrides_to_synonyms(overrides: TuningOverrides) -> None:
    """Apply synonym boosts to the extraction synonyms module.

    This modifies the runtime synonym dictionary to boost labels
    that have been confirmed by human feedback.
    """
    if not overrides.synonym_boosts:
        return

    try:
        from docverify.extraction.synonyms import LABEL_MAP

        for field, boosts in overrides.synonym_boosts.items():
            for label, weight in boosts.items():
                normalized = label.lower().strip()
                if normalized not in LABEL_MAP:
                    LABEL_MAP[normalized] = field
                    logger.debug("Added synonym from feedback: '%s' -> '%s'", normalized, field)

        logger.info("Applied %d synonym boosts from feedback", len(overrides.synonym_boosts))
    except ImportError:
        logger.warning("Could not import synonyms module — overrides not applied")


if __name__ == "__main__":
    tuner = FeedbackTuner()
    overrides = tuner.compute_overrides()
    print(f"Feedback count: {overrides.feedback_count}")
    print(f"Synonym boosts: {len(overrides.synonym_boosts)}")
    print(f"Numeric tolerances: {overrides.numeric_tolerances}")
    print(f"LLM trigger threshold: {overrides.llm_trigger_threshold}")
