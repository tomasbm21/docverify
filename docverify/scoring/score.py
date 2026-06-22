"""Scoring harness — grades pipeline results.json against answer_key.json.

OWNER: Agent 06 (Integration + Scoring)
FROZEN signature per CONTRACTS.md section 5.

Compares the engine's predicted shipment groupings and verdicts to the ground-truth
answer key. The scorer MAY use filenames (the engine may NOT).
"""

import json
import re
from collections import Counter
from pathlib import Path

from docverify.utils import get_logger

logger = get_logger(__name__)

# Map answer_key doc_type short names to engine DocType enum values
_DOC_TYPE_MAP: dict[str, str] = {
    "invoice": "commercial_invoice",
    "bill_of_lading": "bill_of_lading",
    "packing_list": "packing_list",
    "proforma": "proforma_invoice",
    "final_confirmation": "confirmation",
}


def _extract_shipment_prefix(source_path: str) -> str | None:
    """Extract 'S{nn}' prefix from a filename in source_path."""
    basename = Path(source_path).name
    m = re.match(r"(S\d+)", basename, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _map_groups_to_shipments(results: dict) -> dict[str, int]:
    """Map each group_id to a ground-truth shipment number via majority filename prefix.

    Returns {group_id: shipment_number}.
    """
    mapping: dict[str, int] = {}
    for shipment in results["shipments"]:
        gid = shipment["group_id"]
        prefixes: Counter[str] = Counter()
        for doc in shipment["documents"]:
            prefix = _extract_shipment_prefix(doc["source_path"])
            if prefix:
                prefixes[prefix] += 1
        if prefixes:
            dominant = prefixes.most_common(1)[0][0]
            mapping[gid] = int(dominant[1:])
        else:
            mapping[gid] = -1
    return mapping


def _normalize_doc_type(dt: str) -> str:
    """Normalize doc type for comparison between answer key and engine."""
    return _DOC_TYPE_MAP.get(dt, dt)


def score(results_path: str, answer_key_path: str) -> dict:
    """Score pipeline results against the answer key.

    Args:
        results_path: Path to results.json from the reporting stage.
        answer_key_path: Path to answer_key.json (ground truth).

    Returns:
        Scorecard dict with metrics, confusion table, and overall PASS/FAIL.
    """
    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)
    with open(answer_key_path, encoding="utf-8") as f:
        answer_key = json.load(f)

    # Build answer_key lookup: shipment_number -> entry
    ak_by_shipment: dict[int, dict] = {}
    for entry in answer_key["answer_key"]:
        ak_by_shipment[entry["shipment"]] = entry

    # Map predicted groups to ground-truth shipments
    group_to_shipment = _map_groups_to_shipments(results)

    # Build shipment_to_verdict lookup
    shipment_verdict: dict[int, str] = {}
    shipment_data: dict[int, dict] = {}
    for shipment in results["shipments"]:
        gid = shipment["group_id"]
        s_num = group_to_shipment.get(gid, -1)
        if s_num > 0:
            shipment_verdict[s_num] = shipment["verdict"]
            shipment_data[s_num] = shipment

    # -- Grouping accuracy --
    expected_shipments = set(ak_by_shipment.keys())
    predicted_shipments = set(shipment_verdict.keys())

    correct_groupings = sum(1 for s in expected_shipments if s in predicted_shipments)
    grouping_accuracy = correct_groupings / len(expected_shipments) if expected_shipments else 0.0

    # -- Discrepancy detection --
    planted_shipments = {
        s["shipment"] for s in answer_key["answer_key"] if s["has_planted_discrepancy"]
    }
    clean_shipments = {
        s["shipment"] for s in answer_key["answer_key"] if not s["has_planted_discrepancy"]
    }

    true_positives = sum(1 for s in planted_shipments if shipment_verdict.get(s) == "FAIL")
    false_negatives = len(planted_shipments) - true_positives
    recall = true_positives / len(planted_shipments) if planted_shipments else 1.0

    false_positives = sum(1 for s in clean_shipments if shipment_verdict.get(s) == "FAIL")
    true_negatives = len(clean_shipments) - false_positives

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 1.0
    )

    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # -- Localization accuracy --
    localization_correct = 0
    localization_total = 0
    localization_details: list[dict] = []

    for s_num in planted_shipments:
        if shipment_verdict.get(s_num) != "FAIL":
            continue

        ak_entry = ak_by_shipment[s_num]
        expected_doc_type = _normalize_doc_type(ak_entry["discrepancy_in_doc_type"])

        # Extract expected field from discrepancy_detail
        expected_field = None
        if ak_entry["discrepancy_detail"]:
            detail = ak_entry["discrepancy_detail"][0].lower()
            if "order no" in detail or "order_no" in detail:
                expected_field = "order_no"
            elif "container" in detail:
                expected_field = "container_no"
            elif "bl no" in detail or "bl_no" in detail:
                expected_field = "bl_no"
            elif "reference" in detail:
                expected_field = "reference"
            elif "net_kg" in detail or "net kg" in detail or "net weight" in detail:
                expected_field = "net_kg"
            elif "gross_kg" in detail or "gross kg" in detail or "gross weight" in detail:
                expected_field = "gross_kg"
            elif "carton" in detail:
                expected_field = "cartons"
            elif "unit_price" in detail or "unit price" in detail:
                expected_field = "unit_price"
            elif "value" in detail or "amount" in detail or "total" in detail:
                expected_field = "value"

        # Find the HIGH-severity finding
        s_data = shipment_data.get(s_num, {})
        high_findings = [f for f in s_data.get("findings", []) if f["severity"] == "high"]

        found_correct = False
        found_doc_type = None
        found_field = None

        for hf in high_findings:
            suspect_doc_id = hf["doc_b"]
            suspect_doc = None
            for doc in s_data.get("documents", []):
                if doc["doc_id"] == suspect_doc_id:
                    suspect_doc = doc
                    break

            if suspect_doc:
                actual_doc_type = suspect_doc["doc_type"]
                actual_field = hf["field"].split(".")[-1] if "." in hf["field"] else hf["field"]

                found_doc_type = actual_doc_type
                found_field = actual_field

                type_match = actual_doc_type == expected_doc_type
                field_match = expected_field is None or actual_field == expected_field

                if type_match and field_match:
                    found_correct = True
                    break

        localization_total += 1
        if found_correct:
            localization_correct += 1

        localization_details.append({
            "shipment": s_num,
            "expected_doc_type": expected_doc_type,
            "expected_field": expected_field,
            "found_doc_type": found_doc_type,
            "found_field": found_field,
            "correct": found_correct,
        })

    localization_accuracy = (
        localization_correct / localization_total if localization_total > 0 else 0.0
    )

    # -- Confusion table --
    confusion: list[dict] = []
    for s_num in sorted(expected_shipments):
        ak_entry = ak_by_shipment[s_num]
        predicted = shipment_verdict.get(s_num, "N/A")
        is_planted = ak_entry["has_planted_discrepancy"]
        confusion.append({
            "shipment": s_num,
            "planted_error": is_planted,
            "expected_verdict": "FAIL" if is_planted else "PASS",
            "predicted_verdict": predicted,
            "correct": (
                (is_planted and predicted == "FAIL")
                or (not is_planted and predicted == "PASS")
            ),
        })

    # -- Targets --
    targets = {
        "recall_6_of_6": true_positives == 6,
        "zero_false_positives": false_positives == 0,
        "localization_ge_5_of_6": localization_correct >= 5,
        "grouping_12_of_12": correct_groupings == 12,
    }
    overall_pass = all(targets.values())

    scorecard = {
        "grouping_accuracy": f"{correct_groupings}/{len(expected_shipments)}",
        "grouping_accuracy_pct": round(grouping_accuracy * 100, 1),
        "recall": f"{true_positives}/{len(planted_shipments)}",
        "recall_pct": round(recall * 100, 1),
        "precision": round(precision, 3),
        "false_positives": false_positives,
        "f1": round(f1, 3),
        "localization_accuracy": f"{localization_correct}/{localization_total}",
        "localization_accuracy_pct": round(localization_accuracy * 100, 1),
        "targets": targets,
        "overall_pass": overall_pass,
        "confusion_table": confusion,
        "localization_details": localization_details,
    }

    return scorecard


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Score pipeline results against answer key")
    parser.add_argument("--results", type=str, default="data/out/results.json")
    parser.add_argument("--answer-key", type=str, default="../answer_key.json")
    parser.add_argument("--output", type=str, default="data/out/scorecard.json")
    args = parser.parse_args()

    scorecard = score(args.results, args.answer_key)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 50)
    print("SCORECARD")
    print("=" * 50)
    print(f"  Grouping accuracy  : {scorecard['grouping_accuracy']}")
    print(f"  Recall             : {scorecard['recall']}")
    print(f"  Precision          : {scorecard['precision']}")
    print(f"  False positives    : {scorecard['false_positives']}")
    print(f"  F1                 : {scorecard['f1']}")
    print(f"  Localization       : {scorecard['localization_accuracy']}")
    print()
    print("  TARGETS:")
    for k, v in scorecard["targets"].items():
        print(f"    {k}: {'PASS' if v else 'FAIL'}")
    print()
    print(f"  OVERALL: {'PASS' if scorecard['overall_pass'] else 'FAIL'}")
    print("=" * 50)
    print()
    print("CONFUSION TABLE:")
    print(f"  {'Ship':>4}  {'Planted':>7}  {'Expected':>8}  {'Predicted':>9}  {'Correct':>7}")
    print(f"  {'----':>4}  {'-------':>7}  {'--------':>8}  {'---------':>9}  {'-------':>7}")
    for row in scorecard["confusion_table"]:
        print(
            f"  S{row['shipment']:02d}   "
            f"{'YES' if row['planted_error'] else 'no':>7}  "
            f"{row['expected_verdict']:>8}  "
            f"{row['predicted_verdict']:>9}  "
            f"{'OK' if row['correct'] else 'MISS':>7}"
        )


if __name__ == "__main__":
    main()
