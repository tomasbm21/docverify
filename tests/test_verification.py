"""Tests for the cross-reference verifier (Agent D).

Covers: clean groups, identifier mismatches, numeric majority-vote,
tolerance suppression, ambiguous 2-doc groups, and null-field handling.
"""

import pytest

from docverify.schemas.models import (
    CanonicalDoc,
    DocType,
    Finding,
    Identifiers,
    LineItem,
    Logistics,
    Parties,
    Severity,
    ShipmentGroup,
    SourceFormat,
    Totals,
)
from docverify.verification.verify import verify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(
    doc_id: str,
    *,
    order_no: str | None = "ORD-001",
    bl_no: str | None = None,
    container_no: str | None = "CONT-001",
    net_kg: float | None = 6402.0,
    gross_kg: float | None = 7000.0,
    cartons: int | None = 100,
    currency: str | None = "EUR",
    shipper: str | None = "Acme Corp",
    consignee: str | None = "Beta LLC",
    vessel: str | None = "MV Test",
    line_items: list[LineItem] | None = None,
) -> CanonicalDoc:
    return CanonicalDoc(
        doc_id=doc_id,
        source_path=f"/test/{doc_id}.docx",
        doc_type=DocType.commercial_invoice,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(
            order_no=order_no, bl_no=bl_no, container_no=container_no
        ),
        parties=Parties(shipper=shipper, consignee=consignee),
        logistics=Logistics(vessel=vessel),
        totals=Totals(
            net_kg=net_kg,
            gross_kg=gross_kg,
            cartons=cartons,
            currency=currency,
        ),
        line_items=line_items or [],
    )


def _group(group_id: str, doc_ids: list[str]) -> ShipmentGroup:
    return ShipmentGroup(
        group_id=group_id,
        doc_ids=doc_ids,
        grouping_key={"order_no": "ORD-001"},
        match_certainty={did: 0.95 for did in doc_ids},
    )


# ---------------------------------------------------------------------------
# Test: clean group passes with no findings
# ---------------------------------------------------------------------------


def test_clean_group_passes():
    """All fields agree across 3 docs → PASS, no findings."""
    docs = [_doc("a"), _doc("b"), _doc("c")]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)

    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.verdict == "PASS"
    assert v.findings == []
    assert v.suspect_doc_ids == []


# ---------------------------------------------------------------------------
# Test: identifier mismatch → FAIL, HIGH finding, correct suspect
# ---------------------------------------------------------------------------


def test_order_no_mismatch_fails():
    """One doc's order_no differs → FAIL, HIGH finding, that doc is suspect."""
    docs = [
        _doc("a", order_no="ORD-2026-77566"),
        _doc("b", order_no="ORD-2026-77566"),
        _doc("c", order_no="ORD-2026-77567"),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    assert v.verdict == "FAIL"
    assert len(v.findings) >= 1

    order_finding = next(f for f in v.findings if f.field == "identifiers.order_no")
    assert order_finding.severity == Severity.high
    assert order_finding.doc_b == "c"
    assert order_finding.value_a == "ORD-2026-77566"
    assert order_finding.value_b == "ORD-2026-77567"
    assert "c" in v.suspect_doc_ids


# ---------------------------------------------------------------------------
# Test: container_no mismatch → FAIL, HIGH finding
# ---------------------------------------------------------------------------


def test_container_no_mismatch():
    """Container number swap → FAIL, HIGH finding, correct suspect."""
    docs = [
        _doc("a", container_no="SLNM5154974"),
        _doc("b", container_no="SLNM5154974"),
        _doc("c", container_no="SLNM5154974"),
        _doc("d", container_no="BRUX3591184"),
    ]
    groups = [_group("G1", ["a", "b", "c", "d"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    assert v.verdict == "FAIL"
    cont_finding = next(
        f for f in v.findings if f.field == "identifiers.container_no"
    )
    assert cont_finding.severity == Severity.high
    assert cont_finding.doc_b == "d"
    assert "d" in v.suspect_doc_ids


# ---------------------------------------------------------------------------
# Test: net_kg 6,402 vs 6,302 → HIGH finding, correct suspect by majority
# ---------------------------------------------------------------------------


def test_net_kg_mismatch_majority_vote():
    """net_kg 6,402 vs 6,302 → HIGH finding, outlier identified by majority."""
    docs = [
        _doc("a", net_kg=6402.0),
        _doc("b", net_kg=6402.0),
        _doc("c", net_kg=6402.0),
        _doc("d", net_kg=6302.0),
    ]
    groups = [_group("G1", ["a", "b", "c", "d"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    assert v.verdict == "FAIL"
    net_finding = next(f for f in v.findings if f.field == "totals.net_kg")
    assert net_finding.severity == Severity.high
    assert net_finding.doc_a in ("a", "b", "c")  # a consensus doc
    assert net_finding.doc_b == "d"
    assert net_finding.value_a == "6402.0"
    assert net_finding.value_b == "6302.0"
    assert "d" in v.suspect_doc_ids


# ---------------------------------------------------------------------------
# Test: numeric_tolerance suppresses small differences
# ---------------------------------------------------------------------------


def test_numeric_tolerance_suppresses_small_difference():
    """numeric_tolerance=1.0 suppresses a 0.5 kg difference → no finding."""
    docs = [
        _doc("a", net_kg=6402.0),
        _doc("b", net_kg=6402.0),
        _doc("c", net_kg=6402.5),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs, numeric_tolerance=1.0)
    v = verdicts[0]

    assert v.verdict == "PASS"
    net_findings = [f for f in v.findings if "net_kg" in f.field]
    assert net_findings == []


def test_numeric_tolerance_does_not_suppress_large_difference():
    """numeric_tolerance=1.0 does NOT suppress a 100 kg difference."""
    docs = [
        _doc("a", net_kg=6402.0),
        _doc("b", net_kg=6402.0),
        _doc("c", net_kg=6302.0),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs, numeric_tolerance=1.0)
    v = verdicts[0]

    assert v.verdict == "FAIL"
    net_finding = next(f for f in v.findings if f.field == "totals.net_kg")
    assert net_finding.severity == Severity.high
    assert net_finding.doc_b == "c"


# ---------------------------------------------------------------------------
# Test: 2-doc disagreement → both as suspects (ambiguous)
# ---------------------------------------------------------------------------


def test_two_doc_disagreement_both_suspects():
    """2-doc disagreement lists both as suspects with ambiguous message."""
    docs = [
        _doc("a", order_no="ORD-001"),
        _doc("b", order_no="ORD-002"),
    ]
    groups = [_group("G1", ["a", "b"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    assert v.verdict == "FAIL"
    assert "a" in v.suspect_doc_ids
    assert "b" in v.suspect_doc_ids

    order_finding = next(f for f in v.findings if f.field == "identifiers.order_no")
    assert order_finding.severity == Severity.high
    assert "ambiguous" in order_finding.message.lower()


# ---------------------------------------------------------------------------
# Test: null fields never produce findings
# ---------------------------------------------------------------------------


def test_null_fields_no_finding():
    """A null value means 'not present' — never a mismatch."""
    docs = [
        _doc("a", container_no="CONT-001"),
        _doc("b", container_no="CONT-001"),
        _doc("c", container_no=None),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    container_findings = [f for f in v.findings if "container_no" in f.field]
    assert container_findings == []


def test_all_null_field_no_finding():
    """If all docs have null for a field, no finding (fewer than 2 non-null)."""
    docs = [
        _doc("a", bl_no=None),
        _doc("b", bl_no=None),
        _doc("c", bl_no=None),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    bl_findings = [f for f in v.findings if "bl_no" in f.field]
    assert bl_findings == []


# ---------------------------------------------------------------------------
# Test: identifier normalization (separators are ignored)
# ---------------------------------------------------------------------------


def test_identifier_normalization_no_false_positive():
    """Different formatting of the same identifier → no finding."""
    docs = [
        _doc("a", order_no="ORD-2026-77566"),
        _doc("b", order_no="ORD 2026 77566"),
        _doc("c", order_no="ORD202677566"),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    order_findings = [f for f in v.findings if "order_no" in f.field]
    assert order_findings == []
    assert v.verdict == "PASS"


# ---------------------------------------------------------------------------
# Test: parties mismatch → MEDIUM severity
# ---------------------------------------------------------------------------


def test_parties_mismatch_medium_severity():
    """Shipper name mismatch → MEDIUM finding, not HIGH."""
    docs = [
        _doc("a", shipper="Acme Corporation"),
        _doc("b", shipper="Acme Corporation"),
        _doc("c", shipper="Acme Corp Ltd"),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    shipper_finding = next(f for f in v.findings if f.field == "parties.shipper")
    assert shipper_finding.severity == Severity.medium


# ---------------------------------------------------------------------------
# Test: logistics mismatch → LOW severity, group still PASSes
# ---------------------------------------------------------------------------


def test_logistics_mismatch_low_severity_still_passes():
    """Vessel mismatch → LOW finding only; group still PASSes."""
    docs = [
        _doc("a", vessel="MV Alpha"),
        _doc("b", vessel="MV Alpha"),
        _doc("c", vessel="MV Beta"),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    vessel_finding = next(f for f in v.findings if f.field == "logistics.vessel")
    assert vessel_finding.severity == Severity.low
    # LOW-only groups still PASS
    assert v.verdict == "PASS"


# ---------------------------------------------------------------------------
# Test: deterministic ordering of findings
# ---------------------------------------------------------------------------


def test_findings_sorted_by_severity_then_field():
    """Findings are sorted: high before medium before low, then alphabetically."""
    docs = [
        _doc(
            "a",
            order_no="ORD-1",
            shipper="Acme",
            vessel="MV A",
        ),
        _doc(
            "b",
            order_no="ORD-2",
            shipper="Beta",
            vessel="MV B",
        ),
    ]
    groups = [_group("G1", ["a", "b"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    if len(v.findings) >= 2:
        for i in range(len(v.findings) - 1):
            f1 = v.findings[i]
            f2 = v.findings[i + 1]
            order1 = (
                {"high": 0, "medium": 1, "low": 2}[f1.severity.value],
                f1.field,
            )
            order2 = (
                {"high": 0, "medium": 1, "low": 2}[f2.severity.value],
                f2.field,
            )
            assert order1 <= order2


# ---------------------------------------------------------------------------
# Test: line-item comparison by lot
# ---------------------------------------------------------------------------


def test_line_item_mismatch_by_lot():
    """Line items matched by lot; differing net_kg → HIGH finding."""
    docs = [
        _doc(
            "a",
            line_items=[
                LineItem(lot="L1", description="Pasta A", net_kg=500.0, cartons=10),
            ],
        ),
        _doc(
            "b",
            line_items=[
                LineItem(lot="L1", description="Pasta A", net_kg=500.0, cartons=10),
            ],
        ),
        _doc(
            "c",
            line_items=[
                LineItem(lot="L1", description="Pasta A", net_kg=490.0, cartons=10),
            ],
        ),
    ]
    groups = [_group("G1", ["a", "b", "c"])]

    verdicts = verify(groups, docs)
    v = verdicts[0]

    assert v.verdict == "FAIL"
    li_finding = next(
        f for f in v.findings if "line_items[lot=L1].net_kg" == f.field
    )
    assert li_finding.severity == Severity.high
    assert li_finding.doc_b == "c"


# ---------------------------------------------------------------------------
# Test: multiple groups
# ---------------------------------------------------------------------------


def test_multiple_groups_independent():
    """Each group is verified independently."""
    docs = [
        _doc("a", order_no="ORD-1"),
        _doc("b", order_no="ORD-1"),
        _doc("c", order_no="ORD-2"),
        _doc("d", order_no="ORD-3"),  # mismatch
    ]
    groups = [
        _group("G1", ["a", "b"]),
        _group("G2", ["c", "d"]),
    ]

    verdicts = verify(groups, docs)

    assert len(verdicts) == 2
    assert verdicts[0].verdict == "PASS"
    assert verdicts[1].verdict == "FAIL"


# ---------------------------------------------------------------------------
# Test: single-doc group → PASS (can't compare)
# ---------------------------------------------------------------------------


def test_single_doc_group_passes():
    """A group with only 1 doc cannot be compared → PASS."""
    docs = [_doc("a")]
    groups = [_group("G1", ["a"])]

    verdicts = verify(groups, docs)
    assert verdicts[0].verdict == "PASS"
    assert verdicts[0].findings == []
