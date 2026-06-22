"""Tests for the reporting module (Agent 05).

Builds inline verdicts (1 PASS, 1 FAIL) + docs and asserts:
- results.json dict has correct summary counts and the failed shipment's findings + suspect.
- A per-shipment .md report file is created for each group.
- A correction .txt is created for the FAIL group and NOT for the PASS group.
- The correction text names the right field, found vs expected value, and doc type.
"""

import os
import pytest

from docverify.schemas.models import (
    CanonicalDoc,
    DocType,
    Finding,
    Identifiers,
    Parties,
    Severity,
    ShipmentVerdict,
    SourceFormat,
    Totals,
)
from docverify.reporting.report import report


@pytest.fixture
def sample_docs():
    """Two CanonicalDocs for a PASS group and two for a FAIL group."""
    pass_doc1 = CanonicalDoc(
        doc_id="aaa111",
        source_path="S01_BL_v1.docx",
        doc_type=DocType.bill_of_lading,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-2026-10001", bl_no="BL-5001", container_no="CONT-001"),
        parties=Parties(shipper="PastaCo Italia"),
        totals=Totals(cartons=100, net_kg=5000.0, gross_kg=5500.0, value=25000.0, currency="EUR"),
    )
    pass_doc2 = CanonicalDoc(
        doc_id="aaa222",
        source_path="S01_Invoice_v1.docx",
        doc_type=DocType.commercial_invoice,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-2026-10001", bl_no="BL-5001", container_no="CONT-001"),
        parties=Parties(shipper="PastaCo Italia"),
        totals=Totals(cartons=100, net_kg=5000.0, gross_kg=5500.0, value=25000.0, currency="EUR"),
    )

    fail_doc1 = CanonicalDoc(
        doc_id="bbb111",
        source_path="S02_BL_v1.docx",
        doc_type=DocType.bill_of_lading,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-2026-77566", bl_no="BL-6001", container_no="CONT-002"),
        parties=Parties(shipper="Meridiana Foods"),
        totals=Totals(cartons=80, net_kg=4000.0, gross_kg=4400.0, value=18000.0, currency="EUR"),
    )
    fail_doc2 = CanonicalDoc(
        doc_id="bbb222",
        source_path="S02_Invoice_v1.docx",
        doc_type=DocType.commercial_invoice,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-2026-77567", bl_no="BL-6001", container_no="CONT-002"),
        parties=Parties(shipper="Meridiana Foods"),
        totals=Totals(cartons=80, net_kg=4000.0, gross_kg=4400.0, value=18000.0, currency="EUR"),
    )

    return [pass_doc1, pass_doc2, fail_doc1, fail_doc2]


@pytest.fixture
def sample_verdicts():
    """One PASS and one FAIL verdict."""
    pass_verdict = ShipmentVerdict(
        group_id="G01",
        verdict="PASS",
        suspect_doc_ids=[],
        findings=[],
    )
    fail_verdict = ShipmentVerdict(
        group_id="G02",
        verdict="FAIL",
        suspect_doc_ids=["bbb222"],
        findings=[
            Finding(
                group_id="G02",
                field="identifiers.order_no",
                doc_a="bbb111",
                value_a="ORD-2026-77566",
                doc_b="bbb222",
                value_b="ORD-2026-77567",
                severity=Severity.high,
                message="Order number mismatch: ORD-2026-77566 vs ORD-2026-77567",
            )
        ],
    )
    return [pass_verdict, fail_verdict]


def test_results_json_summary(sample_verdicts, sample_docs, tmp_path):
    """results.json has correct summary counts."""
    results = report(sample_verdicts, sample_docs, str(tmp_path))

    assert results["summary"]["shipments"] == 2
    assert results["summary"]["passed"] == 1
    assert results["summary"]["failed"] == 1
    assert results["summary"]["generated_by"] == "docverify"


def test_results_json_shipment_entries(sample_verdicts, sample_docs, tmp_path):
    """results.json has correct shipment entries with findings and suspects."""
    results = report(sample_verdicts, sample_docs, str(tmp_path))

    shipments = {s["group_id"]: s for s in results["shipments"]}

    # PASS shipment
    g01 = shipments["G01"]
    assert g01["verdict"] == "PASS"
    assert g01["suspect_doc_ids"] == []
    assert g01["findings"] == []

    # FAIL shipment
    g02 = shipments["G02"]
    assert g02["verdict"] == "FAIL"
    assert "bbb222" in g02["suspect_doc_ids"]
    assert len(g02["findings"]) == 1
    assert g02["findings"][0]["field"] == "identifiers.order_no"
    assert g02["findings"][0]["value_a"] == "ORD-2026-77566"
    assert g02["findings"][0]["value_b"] == "ORD-2026-77567"
    assert g02["findings"][0]["severity"] == "high"


def test_markdown_reports_created(sample_verdicts, sample_docs, tmp_path):
    """A per-shipment .md report file is created for each group."""
    report(sample_verdicts, sample_docs, str(tmp_path))

    g01_path = tmp_path / "reports" / "G01.md"
    g02_path = tmp_path / "reports" / "G02.md"

    assert g01_path.exists(), "G01.md report should exist"
    assert g02_path.exists(), "G02.md report should exist"


def test_markdown_fail_report_content(sample_verdicts, sample_docs, tmp_path):
    """The FAIL markdown report contains findings table and summary."""
    report(sample_verdicts, sample_docs, str(tmp_path))

    content = (tmp_path / "reports" / "G02.md").read_text(encoding="utf-8")
    assert "FAIL" in content
    assert "order_no" in content
    assert "ORD-2026-77567" in content
    assert "ORD-2026-77566" in content


def test_markdown_pass_report_content(sample_verdicts, sample_docs, tmp_path):
    """The PASS markdown report states all fields agree."""
    report(sample_verdicts, sample_docs, str(tmp_path))

    content = (tmp_path / "reports" / "G01.md").read_text(encoding="utf-8")
    assert "PASS" in content
    assert "All shared fields agree" in content


def test_correction_created_for_fail(sample_verdicts, sample_docs, tmp_path):
    """A correction .txt is created for the FAIL group."""
    report(sample_verdicts, sample_docs, str(tmp_path))

    corr_path = tmp_path / "corrections" / "G02.txt"
    assert corr_path.exists(), "Correction draft should exist for FAIL group"


def test_no_correction_for_pass(sample_verdicts, sample_docs, tmp_path):
    """No correction .txt is created for the PASS group."""
    report(sample_verdicts, sample_docs, str(tmp_path))

    corr_path = tmp_path / "corrections" / "G01.txt"
    assert not corr_path.exists(), "No correction draft should exist for PASS group"


def test_correction_content(sample_verdicts, sample_docs, tmp_path):
    """Correction draft names the right field, found vs expected, and doc type."""
    report(sample_verdicts, sample_docs, str(tmp_path))

    content = (tmp_path / "corrections" / "G02.txt").read_text(encoding="utf-8")

    assert "ORD-2026-77566" in content  # expected / consensus
    assert "ORD-2026-77567" in content  # found / incorrect
    assert "Commercial Invoice" in content or "commercial invoice" in content.lower()
    assert "order no" in content.lower() or "order_no" in content
    assert "Meridiana" in content  # shipper name


def test_results_json_written_to_disk(sample_verdicts, sample_docs, tmp_path):
    """results.json is written to disk and matches the returned dict."""
    results = report(sample_verdicts, sample_docs, str(tmp_path))

    import json
    results_path = tmp_path / "results.json"
    assert results_path.exists()

    with open(results_path, encoding="utf-8") as fh:
        disk_results = json.load(fh)

    assert disk_results["summary"]["shipments"] == results["summary"]["shipments"]
    assert len(disk_results["shipments"]) == len(results["shipments"])


def test_single_pass_shipment(tmp_path):
    """Edge case: only one PASS shipment, no corrections generated."""
    doc = CanonicalDoc(
        doc_id="solo111",
        source_path="Solo_BL.docx",
        doc_type=DocType.bill_of_lading,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-999", bl_no="BL-999"),
        totals=Totals(cartons=10, net_kg=500.0),
    )
    verdict = ShipmentVerdict(group_id="G01", verdict="PASS")
    results = report([verdict], [doc], str(tmp_path))

    assert results["summary"]["passed"] == 1
    assert results["summary"]["failed"] == 0
    assert (tmp_path / "reports" / "G01.md").exists()
    assert not (tmp_path / "corrections" / "G01.txt").exists()


def test_single_fail_shipment_multiple_findings(tmp_path):
    """Edge case: FAIL with multiple findings, correction uses the first one."""
    doc_consensus = CanonicalDoc(
        doc_id="c1",
        source_path="Consensus_BL.docx",
        doc_type=DocType.bill_of_lading,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-500", bl_no="BL-500"),
        parties=Parties(shipper="TestShipper"),
        totals=Totals(cartons=50),
    )
    doc_suspect = CanonicalDoc(
        doc_id="s1",
        source_path="Suspect_INV.docx",
        doc_type=DocType.commercial_invoice,
        source_format=SourceFormat.docx,
        identifiers=Identifiers(order_no="ORD-501", bl_no="BL-500"),
        parties=Parties(shipper="TestShipper"),
        totals=Totals(cartons=49),
    )
    verdict = ShipmentVerdict(
        group_id="G05",
        verdict="FAIL",
        suspect_doc_ids=["s1"],
        findings=[
            Finding(
                group_id="G05",
                field="identifiers.order_no",
                doc_a="c1", value_a="ORD-500",
                doc_b="s1", value_b="ORD-501",
                severity=Severity.high,
                message="Order number mismatch",
            ),
            Finding(
                group_id="G05",
                field="totals.cartons",
                doc_a="c1", value_a="50",
                doc_b="s1", value_b="49",
                severity=Severity.medium,
                message="Carton count mismatch",
            ),
        ],
    )

    results = report([verdict], [doc_consensus, doc_suspect], str(tmp_path))

    assert results["summary"]["failed"] == 1
    assert len(results["shipments"][0]["findings"]) == 2

    corr = (tmp_path / "corrections" / "G05.txt").read_text(encoding="utf-8")
    assert "ORD-500" in corr
    assert "Commercial Invoice" in corr or "commercial invoice" in corr.lower()
