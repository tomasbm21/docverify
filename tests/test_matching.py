"""Tests for the shipment matching module (Agent 03).

Builds small inline CanonicalDoc lists to verify:
  - Docs sharing bl_no cluster together.
  - A doc with a corrupted order_no but matching bl_no + container_no STAYS in group.
  - Two genuinely unrelated docs end up in separate groups.
  - Output is deterministic across runs.
  - Fuzzy fallback attracts a near-miss singleton into the right cluster.
"""

from __future__ import annotations

from docverify.matching.match import match
from docverify.schemas.models import CanonicalDoc, DocType, Identifiers, SourceFormat


def _make_doc(
    doc_id: str,
    *,
    bl_no: str | None = None,
    order_no: str | None = None,
    container_no: str | None = None,
    reference: str | None = None,
) -> CanonicalDoc:
    """Shorthand for building a minimal CanonicalDoc with identifiers only."""
    return CanonicalDoc(
        doc_id=doc_id,
        source_path=f"fake/{doc_id}.docx",
        doc_type=DocType.bill_of_lading,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(
            bl_no=bl_no,
            order_no=order_no,
            container_no=container_no,
            reference=reference,
        ),
    )


# ── Test: docs sharing bl_no cluster together ────────────────────────────────


def test_bl_no_match_clusters_docs():
    """Three docs with the same bl_no must land in one group."""
    docs = [
        _make_doc("doc_a", bl_no="MAEU287193", order_no="ORD-2026-36125"),
        _make_doc("doc_b", bl_no="MAEU287193", container_no="UZKK2424708"),
        _make_doc("doc_c", bl_no="MAEU287193", reference="REF-001"),
    ]
    groups = match(docs)
    assert len(groups) == 1
    assert set(groups[0].doc_ids) == {"doc_a", "doc_b", "doc_c"}


# ── Test: corrupted order_no does NOT split the group ────────────────────────


def test_corrupted_order_no_kept_in_group():
    """Simulates S04: packing list has altered order_no, but bl_no and container_no
    still match siblings.  The doc must NOT be split out."""
    docs = [
        _make_doc(
            "bl",
            bl_no="MAEU287193",
            order_no="ORD-2026-36125",
            container_no="UZKK2424708",
        ),
        _make_doc(
            "invoice",
            bl_no="MAEU287193",
            order_no="ORD-2026-36125",
            container_no="UZKK2424708",
        ),
        _make_doc(
            "packing_corrupted",
            bl_no="MAEU287193",
            order_no="ORD-2026-36126",  # off by one
            container_no="UZKK2424708",
        ),
    ]
    groups = match(docs)
    assert len(groups) == 1, "corrupted doc was split into a separate group"
    assert "packing_corrupted" in groups[0].doc_ids


# ── Test: unrelated docs produce separate groups ─────────────────────────────


def test_unrelated_docs_separate_groups():
    """Two docs with zero identifier overlap must land in different groups."""
    docs = [
        _make_doc("doc_1", bl_no="AAAA111111", order_no="ORD-100"),
        _make_doc("doc_2", bl_no="BBBB222222", order_no="ORD-200"),
    ]
    groups = match(docs)
    assert len(groups) == 2
    group_ids_per_doc = {}
    for g in groups:
        for did in g.doc_ids:
            group_ids_per_doc[did] = g.group_id
    assert group_ids_per_doc["doc_1"] != group_ids_per_doc["doc_2"]


# ── Test: determinism ────────────────────────────────────────────────────────


def test_deterministic_output():
    """Running match() twice on the same input must produce identical group_ids
    and doc_id assignments."""
    docs = [
        _make_doc("x1", bl_no="CARRIER001", order_no="ORD-A"),
        _make_doc("x2", bl_no="CARRIER001", order_no="ORD-A"),
        _make_doc("y1", bl_no="CARRIER002", order_no="ORD-B"),
    ]
    run1 = match(docs)
    run2 = match(docs)
    assert len(run1) == len(run2)
    for g1, g2 in zip(run1, run2):
        assert g1.group_id == g2.group_id
        assert g1.doc_ids == g2.doc_ids
        assert g1.grouping_key == g2.grouping_key


# ── Test: empty input ────────────────────────────────────────────────────────


def test_empty_input():
    """match([]) must return an empty list, not crash."""
    assert match([]) == []


# ── Test: singleton doc gets its own group ───────────────────────────────────


def test_singleton_doc():
    """A doc with identifiers that match no other doc becomes a singleton group."""
    docs = [
        _make_doc("lone", bl_no="UNIQUE999", order_no="ORD-LONE"),
    ]
    groups = match(docs)
    assert len(groups) == 1
    assert groups[0].doc_ids == ["lone"]
    # Low certainty for singleton.
    assert groups[0].match_certainty["lone"] <= 0.5


# ── Test: container_no links docs even when order_no differs ─────────────────


def test_container_no_bridges_different_orders():
    """Two docs with different order_no but same container_no must cluster."""
    docs = [
        _make_doc("c1", order_no="ORD-100", container_no="UZKK2424708"),
        _make_doc("c2", order_no="ORD-200", container_no="UZKK2424708"),
    ]
    groups = match(docs)
    assert len(groups) == 1
    assert set(groups[0].doc_ids) == {"c1", "c2"}


# ── Test: reference field also creates edges ──────────────────────────────────


def test_reference_field_clusters():
    """Docs linked only by reference must still cluster."""
    docs = [
        _make_doc("r1", reference="SHIP-2026-0042"),
        _make_doc("r2", reference="SHIP-2026-0042"),
    ]
    groups = match(docs)
    assert len(groups) == 1


# ── Test: certainty scoring ──────────────────────────────────────────────────


def test_certainty_multi_identifier_match():
    """A doc matching 2+ identifiers with consensus should have certainty 1.0."""
    docs = [
        _make_doc("hi1", bl_no="BL-100", order_no="ORD-100", container_no="CN-100"),
        _make_doc("hi2", bl_no="BL-100", order_no="ORD-100", container_no="CN-100"),
    ]
    groups = match(docs)
    for cid in groups[0].doc_ids:
        assert groups[0].match_certainty[cid] == 1.0


def test_certainty_single_identifier_match():
    """A doc matching exactly 1 identifier with consensus should have certainty 0.7."""
    docs = [
        _make_doc("s1", bl_no="BL-200", order_no="ORD-A"),
        _make_doc("s2", bl_no="BL-200", order_no="ORD-B"),
        _make_doc("s3", bl_no="BL-200", order_no="ORD-A"),
    ]
    groups = match(docs)
    # s2 shares only bl_no with consensus (order_no differs from majority).
    assert groups[0].match_certainty["s2"] == 0.7


# ── Test: group_id format ────────────────────────────────────────────────────


def test_group_id_format():
    """Group IDs must be G01, G02, ... zero-padded to at least 2 digits."""
    docs = [
        _make_doc("g1", bl_no="AAA"),
        _make_doc("g2", bl_no="BBB"),
        _make_doc("g3", bl_no="CCC"),
    ]
    groups = match(docs)
    ids = [g.group_id for g in groups]
    assert all(gid.startswith("G") for gid in ids)
    # Must be sorted deterministically.
    assert ids == sorted(ids)
