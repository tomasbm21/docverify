"""Cross-Reference Verifier — compares fields across grouped documents.

OWNER: Agent 04 (Verification)
FROZEN signatures per CONTRACTS.md §5.

For each shipment group, compares every shared field across its documents,
flags mismatches with severity, and decides PASS/FAIL plus which document
is the likely culprit (majority vote).
"""

import json
from pathlib import Path

from docverify.schemas.models import (
    CanonicalDoc,
    Finding,
    Severity,
    ShipmentGroup,
    ShipmentVerdict,
)
from docverify.utils import get_logger, normalize_identifier

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Severity ordering for stable sort of findings
_SEV_ORDER: dict[Severity, int] = {
    Severity.high: 0,
    Severity.medium: 1,
    Severity.low: 2,
}

# Verdict threshold: FAIL if any finding has severity >= this level.
# Exposed as a named constant so it is easy to tune.
FAIL_SEVERITIES: set[Severity] = {Severity.high, Severity.medium}

# Field groups and their canonical comparison rules
_IDENTIFIER_FIELDS = ("order_no", "bl_no", "reference", "container_no", "seal_no")
_TOTALS_NUMERIC_FIELDS = ("net_kg", "gross_kg", "value")
_TOTALS_COUNT_FIELDS = ("cartons",)
_PARTY_FIELDS = ("shipper", "consignee")
_LOGISTICS_FIELDS = ("vessel", "voyage", "pol", "pod", "ship_date")
_LI_NUMERIC_FIELDS = ("net_kg", "gross_kg", "unit_price", "amount")
_LI_COUNT_FIELDS = ("cartons",)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_str(val: object) -> str | None:
    """Convert a value to its string representation for display in a Finding."""
    if val is None:
        return None
    return str(val)


def _normalize_party(val: str | None) -> str | None:
    """Normalize a party name: lowercase, collapse whitespace."""
    if val is None:
        return None
    return " ".join(str(val).lower().split())


def _compare_section(
    group_id: str,
    members: list[CanonicalDoc],
    section: str,
    fields: tuple[str, ...],
    severity: Severity,
    normalize_fn: object | None = None,
    tolerance: float = 0.0,
) -> list[Finding]:
    """Compare *fields* in *section* across *members*.

    Returns a Finding for every doc whose value deviates from the majority.
    """
    findings: list[Finding] = []

    for field in fields:
        # Collect non-null values
        values: dict[str, object] = {}
        for doc in members:
            section_obj = getattr(doc, section, None)
            if section_obj is None:
                continue
            val = getattr(section_obj, field, None)
            if val is not None:
                values[doc.doc_id] = val

        # Need at least 2 docs with non-null values to compare
        if len(values) < 2:
            continue

        # Group by (normalized) value
        groups: dict[object, list[str]] = {}
        for did, val in values.items():
            key = normalize_fn(val) if normalize_fn else val
            groups.setdefault(key, []).append(did)

        # All agree → no finding
        if len(groups) <= 1:
            continue

        # Majority vote: largest group is the consensus
        sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
        majority_docs = sorted_groups[0][1]
        majority_val = values[majority_docs[0]]

        is_ambiguous = len(values) == 2 and len(groups) == 2

        field_path = f"{section}.{field}"

        for _key, doc_ids in sorted_groups[1:]:
            for did in doc_ids:
                dev_val = values[did]

                # Tolerance check for numeric fields
                if (
                    tolerance > 0
                    and isinstance(majority_val, (int, float))
                    and isinstance(dev_val, (int, float))
                ):
                    if abs(float(majority_val) - float(dev_val)) <= tolerance:
                        continue  # within tolerance → suppress finding

                # Build human-readable message
                if is_ambiguous:
                    msg = (
                        f"{field_path} mismatch: "
                        f"{_to_str(majority_val)} vs {_to_str(dev_val)}"
                        f" (ambiguous -- only 2 docs)"
                    )
                else:
                    msg = (
                        f"{field_path} mismatch: "
                        f"{len(majority_docs)} of {len(values)} docs show "
                        f"{_to_str(majority_val)}, doc shows {_to_str(dev_val)}"
                    )

                findings.append(
                    Finding(
                        group_id=group_id,
                        field=field_path,
                        doc_a=majority_docs[0],
                        value_a=_to_str(majority_val),
                        doc_b=did,
                        value_b=_to_str(dev_val),
                        severity=severity,
                        message=msg,
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Line-item comparison
# ---------------------------------------------------------------------------


def _compare_li_values(
    group_id: str,
    field_prefix: str,
    doc_items: dict[str, object],
    numeric_tolerance: float,
) -> list[Finding]:
    """Compare numeric/count fields across matched line items."""
    findings: list[Finding] = []

    for field in _LI_NUMERIC_FIELDS + _LI_COUNT_FIELDS:
        values: dict[str, object] = {}
        for did, item in doc_items.items():
            val = getattr(item, field, None)
            if val is not None:
                values[did] = val

        if len(values) < 2:
            continue

        # Group by exact value
        groups: dict[object, list[str]] = {}
        for did, val in values.items():
            groups.setdefault(val, []).append(did)

        if len(groups) <= 1:
            continue

        sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
        majority_docs = sorted_groups[0][1]
        majority_val = values[majority_docs[0]]

        is_ambiguous = len(values) == 2 and len(groups) == 2

        field_path = f"{field_prefix}.{field}"

        for _key, doc_ids in sorted_groups[1:]:
            for did in doc_ids:
                dev_val = values[did]

                # Tolerance for numeric (non-count) fields
                if (
                    field not in _LI_COUNT_FIELDS
                    and numeric_tolerance > 0
                    and isinstance(majority_val, (int, float))
                    and isinstance(dev_val, (int, float))
                ):
                    if abs(float(majority_val) - float(dev_val)) <= numeric_tolerance:
                        continue

                if is_ambiguous:
                    msg = (
                        f"{field_path} mismatch: "
                        f"{_to_str(majority_val)} vs {_to_str(dev_val)}"
                        f" (ambiguous -- only 2 docs)"
                    )
                else:
                    msg = (
                        f"{field_path} mismatch: "
                        f"{len(majority_docs)} of {len(values)} docs show "
                        f"{_to_str(majority_val)}, doc shows {_to_str(dev_val)}"
                    )

                findings.append(
                    Finding(
                        group_id=group_id,
                        field=field_path,
                        doc_a=majority_docs[0],
                        value_a=_to_str(majority_val),
                        doc_b=did,
                        value_b=_to_str(dev_val),
                        severity=Severity.high,
                        message=msg,
                    )
                )

    return findings


def _compare_line_items(
    group_id: str,
    members: list[CanonicalDoc],
    numeric_tolerance: float,
) -> list[Finding]:
    """Match line items across docs by lot (fallback: normalized description),
    then compare numeric fields for each matched set."""
    findings: list[Finding] = []

    # Track which item indices are already matched by lot per doc
    matched: dict[str, set[int]] = {doc.doc_id: set() for doc in members}

    # --- Pass 1: match by lot ---
    lot_map: dict[str, dict[str, tuple[int, object]]] = {}
    for doc in members:
        for idx, item in enumerate(doc.line_items):
            if item.lot:
                lot_map.setdefault(item.lot, {})[doc.doc_id] = (idx, item)

    for lot, doc_entries in lot_map.items():
        prefix = f"line_items[lot={lot}]"
        if len(doc_entries) >= 2:
            doc_items = {did: entry[1] for did, entry in doc_entries.items()}
            findings.extend(
                _compare_li_values(group_id, prefix, doc_items, numeric_tolerance)
            )
            for did, entry in doc_entries.items():
                matched[did].add(entry[0])
        elif len(doc_entries) == 1:
            # Unmatched: only one doc has this lot
            did, (idx, item) = next(iter(doc_entries.items()))
            label = item.lot or item.description or "unknown"
            findings.append(
                Finding(
                    group_id=group_id,
                    field=prefix,
                    doc_a=did,
                    value_a=str(label),
                    doc_b=did,
                    value_b="not present in other documents",
                    severity=Severity.low,
                    message=f"Line item '{label}' only found in one document",
                )
            )

    # --- Pass 2: match remaining items by normalized description ---
    desc_map: dict[str, dict[str, tuple[int, object]]] = {}
    for doc in members:
        for idx, item in enumerate(doc.line_items):
            if idx in matched[doc.doc_id]:
                continue  # already matched by lot
            if item.description:
                norm = " ".join(item.description.lower().split())
                desc_map.setdefault(norm, {})[doc.doc_id] = (idx, item)

    for desc, doc_entries in desc_map.items():
        prefix = f"line_items[desc={desc}]"
        if len(doc_entries) >= 2:
            doc_items = {did: entry[1] for did, entry in doc_entries.items()}
            findings.extend(
                _compare_li_values(group_id, prefix, doc_items, numeric_tolerance)
            )
            for did, entry in doc_entries.items():
                matched[did].add(entry[0])
        elif len(doc_entries) == 1:
            did, (idx, item) = next(iter(doc_entries.items()))
            label = item.description or "unknown"
            findings.append(
                Finding(
                    group_id=group_id,
                    field=prefix,
                    doc_a=did,
                    value_a=str(label),
                    doc_b=did,
                    value_b="not present in other documents",
                    severity=Severity.low,
                    message=f"Line item '{label}' only found in one document",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Suspect (majority-vote outlier) collection
# ---------------------------------------------------------------------------


def _collect_suspects(
    findings: list[Finding], members: list[CanonicalDoc]
) -> list[str]:
    """Collect doc_ids that are in the minority across findings.

    For every finding, doc_b is the outlier.  In a 2-doc ambiguous disagreement
    both docs are listed as suspects since we cannot determine the outlier.
    """
    suspects: set[str] = set()
    for f in findings:
        suspects.add(f.doc_b)
    # 2-doc ambiguous case: both are suspects
    if len(members) == 2 and findings:
        for doc in members:
            suspects.add(doc.doc_id)
    return sorted(suspects)


# ---------------------------------------------------------------------------
# Public API (frozen signature per CONTRACTS.md §5)
# ---------------------------------------------------------------------------


def verify(
    groups: list[ShipmentGroup],
    docs: list[CanonicalDoc],
    numeric_tolerance: float = 0.0,
) -> list[ShipmentVerdict]:
    """Verify each shipment group and return per-shipment verdicts.

    For each group, compares every shared field across member documents.
    Flags mismatches with severity, determines the likely outlier document
    via majority vote, and assigns PASS/FAIL.

    Args:
        groups: Shipment groups from the matching stage.
        docs: All canonical documents (indexed by doc_id).
        numeric_tolerance: Maximum allowed numeric difference before flagging.
            Default 0.0 = exact match.

    Returns:
        One ShipmentVerdict per group, in the same order as *groups*.
    """
    doc_map: dict[str, CanonicalDoc] = {d.doc_id: d for d in docs}
    verdicts: list[ShipmentVerdict] = []

    for group in groups:
        members = [doc_map[did] for did in group.doc_ids if did in doc_map]

        if len(members) < 2:
            # Cannot compare with fewer than 2 documents
            verdicts.append(
                ShipmentVerdict(group_id=group.group_id, verdict="PASS")
            )
            continue

        findings: list[Finding] = []

        # 1. Identifiers — exact match after normalize_identifier → HIGH
        findings.extend(
            _compare_section(
                group.group_id,
                members,
                "identifiers",
                _IDENTIFIER_FIELDS,
                severity=Severity.high,
                normalize_fn=normalize_identifier,
            )
        )

        # 2. Totals numeric fields — numeric compare with tolerance → HIGH
        findings.extend(
            _compare_section(
                group.group_id,
                members,
                "totals",
                _TOTALS_NUMERIC_FIELDS,
                severity=Severity.high,
                tolerance=numeric_tolerance,
            )
        )

        # 3. Totals count fields — exact int match → HIGH
        findings.extend(
            _compare_section(
                group.group_id,
                members,
                "totals",
                _TOTALS_COUNT_FIELDS,
                severity=Severity.high,
            )
        )

        # 4. Currency — exact match → HIGH
        findings.extend(
            _compare_section(
                group.group_id,
                members,
                "totals",
                ("currency",),
                severity=Severity.high,
            )
        )

        # 5. Parties — normalized string compare → MEDIUM
        findings.extend(
            _compare_section(
                group.group_id,
                members,
                "parties",
                _PARTY_FIELDS,
                severity=Severity.medium,
                normalize_fn=_normalize_party,
            )
        )

        # 6. Logistics — compare when >=2 docs have value → LOW
        findings.extend(
            _compare_section(
                group.group_id,
                members,
                "logistics",
                _LOGISTICS_FIELDS,
                severity=Severity.low,
                normalize_fn=_normalize_party,
            )
        )

        # 7. Line-item level comparison
        findings.extend(
            _compare_line_items(group.group_id, members, numeric_tolerance)
        )

        # 8. Collect suspects via majority vote
        suspect_ids = _collect_suspects(findings, members)

        # 9. Verdict: FAIL if any HIGH or MEDIUM finding exists
        has_fail = any(f.severity in FAIL_SEVERITIES for f in findings)
        verdict = "FAIL" if has_fail else "PASS"

        # 10. Sort findings by severity (high first) then by field path
        findings.sort(key=lambda f: (_SEV_ORDER[f.severity], f.field))

        verdicts.append(
            ShipmentVerdict(
                group_id=group.group_id,
                verdict=verdict,
                suspect_doc_ids=suspect_ids,
                findings=findings,
            )
        )

    return verdicts


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Cross-reference verification stage")
    parser.add_argument(
        "--in-dir", default="data/out",
        help="Input directory containing groups.json and canonical_docs.json (default: data/out)",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output JSON path (default: <in-dir>/verdicts.json)",
    )
    parser.add_argument(
        "--numeric-tolerance", type=float, default=0.0,
        help="Numeric comparison tolerance (default: 0.0)",
    )
    args = parser.parse_args()

    base = Path(args.in_dir)
    groups_path = base / "groups.json"
    docs_path = base / "canonical_docs.json"
    out_path = Path(args.output) if args.output else base / "verdicts.json"

    # BUG-015: check files exist before reading
    if not groups_path.exists():
        print(f"Error: {groups_path} not found. Run matching first.", file=sys.stderr)
        sys.exit(1)
    if not docs_path.exists():
        print(f"Error: {docs_path} not found. Run extraction first.", file=sys.stderr)
        sys.exit(1)

    groups = [ShipmentGroup(**g) for g in json.loads(groups_path.read_text())]
    docs = [CanonicalDoc(**d) for d in json.loads(docs_path.read_text())]

    verdicts = verify(groups, docs, numeric_tolerance=args.numeric_tolerance)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([v.model_dump(mode="json") for v in verdicts], indent=2)
    )
    print(f"Wrote {len(verdicts)} verdicts to {out_path}")
