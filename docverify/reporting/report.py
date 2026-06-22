"""Reporter -- aggregates findings into human-readable reports and machine-readable JSON.

OWNER: Agent 05 (Reporting)
FROZEN signatures per CONTRACTS.md section 5.

Consumes:  list[ShipmentVerdict] + list[CanonicalDoc]
Produces:  results.json, reports/*.md, corrections/*.txt
"""

import json
import os
from datetime import datetime, timezone

from docverify.schemas.models import CanonicalDoc, Finding, Severity, ShipmentVerdict
from docverify.utils import get_logger

logger = get_logger(__name__)


def _build_doc_index(docs: list[CanonicalDoc]) -> dict[str, CanonicalDoc]:
    """Map doc_id -> CanonicalDoc for fast lookup."""
    return {doc.doc_id: doc for doc in docs}


def _finding_as_dict(f: Finding) -> dict:
    """Serialize a Finding to the results.json shape."""
    return {
        "field": f.field,
        "doc_a": f.doc_a,
        "value_a": f.value_a,
        "doc_b": f.doc_b,
        "value_b": f.value_b,
        "severity": f.severity.value,
        "message": f.message,
    }


def _doc_summary(doc: CanonicalDoc) -> dict:
    """Serialize a doc reference for the results.json documents list."""
    return {
        "doc_id": doc.doc_id,
        "doc_type": doc.doc_type.value,
        "source_path": doc.source_path,
    }


def _consensus_identifiers(verdict: ShipmentVerdict, doc_index: dict[str, CanonicalDoc]) -> dict[str, str | None]:
    """Extract consensus identifiers from the non-suspect docs in the group.

    Falls back to all docs if no suspects or all docs are suspects.
    """
    all_ids = [doc_index[did] for did in _doc_ids_for_verdict(verdict, doc_index)]
    non_suspect = [d for d in all_ids if d.doc_id not in verdict.suspect_doc_ids]
    if not non_suspect:
        non_suspect = all_ids

    def majority(field: str) -> str | None:
        vals = [getattr(d.identifiers, field) for d in non_suspect if getattr(d.identifiers, field)]
        if not vals:
            return None
        from collections import Counter
        return Counter(vals).most_common(1)[0][0]

    return {
        "order_no": majority("order_no"),
        "bl_no": majority("bl_no"),
        "container_no": majority("container_no"),
    }


def _totals_from_docs(verdict: ShipmentVerdict, doc_index: dict[str, CanonicalDoc]) -> dict[str, str | None]:
    """Extract consensus totals from the non-suspect docs."""
    all_ids = [doc_index[did] for did in _doc_ids_for_verdict(verdict, doc_index)]
    non_suspect = [d for d in all_ids if d.doc_id not in verdict.suspect_doc_ids]
    if not non_suspect:
        non_suspect = all_ids

    def majority(field: str) -> str | None:
        vals = []
        for d in non_suspect:
            v = getattr(d.totals, field)
            if v is not None:
                vals.append(str(v))
        if not vals:
            return None
        from collections import Counter
        return Counter(vals).most_common(1)[0][0]

    return {
        "cartons": majority("cartons"),
        "net_kg": majority("net_kg"),
        "gross_kg": majority("gross_kg"),
        "value": majority("value"),
        "currency": majority("currency"),
    }


def _doc_ids_for_verdict(verdict: ShipmentVerdict, doc_index: dict[str, CanonicalDoc]) -> list[str]:
    """Collect doc_ids referenced in the verdict's findings + suspects, plus any in doc_index
    that belong to this group.

    Since we don't have the original ShipmentGroup, we reconstruct from findings + suspects.
    For a PASS verdict with no findings/suspects, we need the full group -- but the verdict
    alone doesn't carry doc_ids. We rely on the caller providing docs that match this group.
    """
    ids = set(verdict.suspect_doc_ids)
    for f in verdict.findings:
        ids.add(f.doc_a)
        ids.add(f.doc_b)
    return list(ids) if ids else []


def _write_markdown_report(group_id: str, verdict: ShipmentVerdict,
                           group_docs: list[CanonicalDoc],
                           out_dir: str,
                           doc_index: dict[str, CanonicalDoc]) -> None:
    """Write a per-shipment human-readable markdown report."""
    lines: list[str] = []
    tag = verdict.verdict
    lines.append(f"# Shipment Report — {group_id}")
    lines.append("")
    lines.append(f"**Verdict:** {tag}")
    lines.append("")

    # Identifiers
    if group_docs:
        # Use the first non-suspect doc's identifiers as display
        display_doc = None
        for d in group_docs:
            if d.doc_id not in verdict.suspect_doc_ids:
                display_doc = d
                break
        if display_doc is None and group_docs:
            display_doc = group_docs[0]

        ids = display_doc.identifiers
        lines.append(f"**Order No:** {ids.order_no or 'N/A'}  ")
        lines.append(f"**B/L No:** {ids.bl_no or 'N/A'}  ")
        lines.append(f"**Container No:** {ids.container_no or 'N/A'}")
        lines.append("")
        lines.append(f"**Documents:** {len(group_docs)}")
    lines.append("")

    # Document list
    lines.append("## Documents")
    lines.append("")
    for doc in group_docs:
        lines.append(f"- **{doc.doc_type.value}** — `{doc.source_path}`")
    lines.append("")

    if verdict.verdict == "FAIL":
        # Separate findings by severity: actionable (HIGH/MEDIUM) vs minor (LOW)
        actionable = [f for f in verdict.findings if f.severity in (Severity.high, Severity.medium)]
        minor = [f for f in verdict.findings if f.severity == Severity.low]

        # Actionable findings table
        if actionable:
            lines.append("## Findings")
            lines.append("")
            lines.append("| Field | Suspect Doc | Found Value | Expected Value | Severity |")
            lines.append("|-------|------------|-------------|----------------|----------|")
            for f in actionable:
                suspect_doc = doc_index.get(f.doc_b)
                suspect_name = suspect_doc.source_path if suspect_doc else f.doc_b
                lines.append(f"| {f.field} | `{suspect_name}` | {f.value_b or 'N/A'} | {f.value_a or 'N/A'} | {f.severity.value} |")
            lines.append("")

        # Minor observations in a separate section so they don't drown out real errors
        if minor:
            lines.append("## Minor Observations")
            lines.append("")
            lines.append(
                f"The following {len(minor)} low-severity differences were also noted "
                f"(format variations, items only in one document, etc.):"
            )
            lines.append("")
            lines.append("| Field | Detail |")
            lines.append("|-------|--------|")
            for f in minor:
                lines.append(f"| {f.field} | {f.message} |")
            lines.append("")

        # Plain-English summary based on the first actionable finding
        if actionable and group_docs:
            first_finding = actionable[0]
            suspect_doc = doc_index.get(first_finding.doc_b)
            suspect_name = suspect_doc.doc_type.value if suspect_doc else "unknown document"
            suspect_path = suspect_doc.source_path if suspect_doc else ""
            n_other = len([d for d in group_docs if d.doc_id not in verdict.suspect_doc_ids])
            doc_word = "document" if n_other == 1 else "documents"
            lines.append(f"**Summary:** Likely error: the {suspect_name.replace('_', ' ').title()}"
                         f" (`{suspect_path}`) — {first_finding.field.split('.')[-1].replace('_', ' ')}"
                         f" disagrees with {n_other} other {doc_word} in this shipment.")
        lines.append("")
    else:
        n_docs = len(group_docs)
        doc_word = "document" if n_docs == 1 else "documents"

        if n_docs == 1:
            # Single-document group -- no cross-reference was possible
            lines.append(
                "Insufficient documents for cross-reference "
                f"({n_docs} {doc_word} in group). "
                "No comparison performed."
            )
            lines.append("")
        else:
            # PASS verdict: show low-severity observations if any exist (BUG-029)
            minor = [f for f in verdict.findings if f.severity == Severity.low]
            if minor:
                lines.append(f"All critical fields agree across {n_docs} {doc_word}.")
                lines.append("")
                lines.append(f"However, {len(minor)} minor observation(s) were noted:")
                lines.append("")
                lines.append("| Field | Detail |")
                lines.append("|-------|--------|")
                for f in minor:
                    lines.append(f"| {f.field} | {f.message} |")
                lines.append("")
            else:
                lines.append(f"All shared fields agree across {n_docs} {doc_word}.")
                lines.append("")

    md_path = os.path.join(out_dir, "reports", f"{group_id}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _write_correction_draft(group_id: str, verdict: ShipmentVerdict,
                            group_docs: list[CanonicalDoc],
                            doc_index: dict[str, CanonicalDoc],
                            out_dir: str) -> None:
    """Write a correction-request email draft for a FAIL shipment (draft only -- never send)."""
    # Filter to actionable findings (HIGH and MEDIUM) -- skip LOW-only verdicts
    actionable = [f for f in verdict.findings if f.severity in (Severity.high, Severity.medium)]
    if not actionable:
        return

    # Get identifiers from the first actionable finding's consensus doc
    first_f = actionable[0]
    consensus_doc = doc_index.get(first_f.doc_a)

    order_no = (consensus_doc.identifiers.order_no if consensus_doc else None) or "N/A"
    bl_no = (consensus_doc.identifiers.bl_no if consensus_doc else None) or "N/A"
    container_no = (consensus_doc.identifiers.container_no if consensus_doc else None) or "N/A"
    shipper = (consensus_doc.parties.shipper if consensus_doc else None) or "Shipper"

    n_other = len([d for d in group_docs if d.doc_id not in verdict.suspect_doc_ids])
    doc_word = "document" if n_other == 1 else "documents"

    # Build discrepancy list covering ALL actionable findings
    discrepancies = []
    for f in actionable:
        f_suspect = doc_index.get(f.doc_b)
        f_doc_type = (f_suspect.doc_type.value.replace("_", " ").title()
                      if f_suspect else "document")
        f_field_name = f.field.split(".")[-1].replace("_", " ")
        discrepancies.append(
            f"  - {f_doc_type} ({f_field_name}): shows \"{f.value_b}\" but should be "
            f"\"{f.value_a}\" per the other {n_other} {doc_word} in this shipment."
        )

    discrepancies_text = "\n".join(discrepancies)

    text = f"""Subject: Correction needed — Order {order_no} / B/L {bl_no}

Dear {shipper},

While cross-checking the documents for shipment {order_no} (B/L {bl_no}, container {container_no}) we found discrepancy(ies) that need correction:

{discrepancies_text}

Please reissue the corrected document(s) at your earliest convenience so we can clear the shipment without delay.

Best regards,
Logistics Team"""

    corr_path = os.path.join(out_dir, "corrections", f"{group_id}.txt")
    with open(corr_path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _generate_results_dashboard(results: dict, out_dir: str) -> None:
    """Write a self-contained dashboard.html with inline results data (no fetch needed)."""
    results_json = json.dumps(results, ensure_ascii=False)
    timestamp = results["summary"]["timestamp"]
    total = results["summary"]["shipments"]
    passed = results["summary"]["passed"]
    failed = results["summary"]["failed"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DocVerify Results Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 960px; margin: 40px auto; padding: 0 20px;
         background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ color: #00d4aa; border-bottom: 2px solid #00d4aa; padding-bottom: 10px; }}
  h2 {{ color: #00d4aa; margin-top: 32px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 20px 0; }}
  .stat {{ background: #16213e; padding: 16px; border-radius: 8px; text-align: center; }}
  .stat .value {{ font-size: 28px; font-weight: bold; }}
  .stat .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
  .good {{ color: #4ade80; }}
  .warn {{ color: #fbbf24; }}
  .bad {{ color: #f87171; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #2a2a4a; }}
  th {{ color: #00d4aa; cursor: pointer; }}
  th:hover {{ color: #00ffcc; }}
  tr:hover {{ background: #16213e; }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
  .badge-pass {{ background: #064e3b; color: #4ade80; }}
  .badge-fail {{ background: #7f1d1d; color: #f87171; }}
  .filter {{ margin: 16px 0; }}
  .filter button {{ background: #16213e; color: #e0e0e0; border: 1px solid #2a2a4a;
                    padding: 6px 16px; border-radius: 4px; cursor: pointer; margin-right: 8px; }}
  .filter button.active {{ background: #00d4aa; color: #1a1a2e; border-color: #00d4aa; }}
  details {{ margin: 8px 0; }}
  summary {{ cursor: pointer; color: #aaa; }}
  .timestamp {{ color: #666; font-size: 14px; }}
</style>
</head>
<body>
<h1>DocVerify Results Dashboard</h1>
<p class="timestamp">Generated: {timestamp}</p>

<div class="stats">
  <div class="stat">
    <div class="value">{total}</div>
    <div class="label">Total Shipments</div>
  </div>
  <div class="stat">
    <div class="value good">{passed}</div>
    <div class="label">Passed</div>
  </div>
  <div class="stat">
    <div class="value bad">{failed}</div>
    <div class="label">Failed</div>
  </div>
  <div class="stat">
    <div class="value">{len(results["shipments"][0]["documents"]) if results["shipments"] else 0}+</div>
    <div class="label">Documents</div>
  </div>
</div>

<div class="filter">
  <button class="active" onclick="filterShipments('all')">All</button>
  <button onclick="filterShipments('PASS')">PASS</button>
  <button onclick="filterShipments('FAIL')">FAIL</button>
</div>

<table>
  <thead>
    <tr><th>Group</th><th>Verdict</th><th>Documents</th><th>Findings</th><th>Order No</th><th>B/L No</th></tr>
  </thead>
  <tbody id="shipments-body"></tbody>
</table>

<div id="detail-panel"></div>

<script>
const DATA = {results_json};

function render() {{
  const tbody = document.getElementById("shipments-body");
  tbody.innerHTML = "";
  const filter = document.querySelector(".filter button.active").textContent;
  DATA.shipments.forEach(s => {{
    if (filter !== "all" && s.verdict !== filter) return;
    const tr = document.createElement("tr");
    const badge = s.verdict === "PASS"
      ? '<span class="badge badge-pass">PASS</span>'
      : '<span class="badge badge-fail">FAIL</span>';
    const ids = s.identifiers || {{}};
    tr.innerHTML = `
      <td>${{s.group_id}}</td>
      <td>${{badge}}</td>
      <td>${{s.documents.length}}</td>
      <td>${{s.findings.length}}</td>
      <td>${{ids.order_no || "N/A"}}</td>
      <td>${{ids.bl_no || "N/A"}}</td>`;
    tr.style.cursor = "pointer";
    tr.onclick = () => showDetail(s);
    tbody.appendChild(tr);
  }});
}}

function filterShipments(type) {{
  document.querySelectorAll(".filter button").forEach(b => b.classList.remove("active"));
  event.target.classList.add("active");
  render();
}}

function showDetail(s) {{
  const panel = document.getElementById("detail-panel");
  let html = `<h2>${{s.group_id}} — ${{s.verdict}}</h2>`;
  html += `<p><strong>Documents:</strong></p><ul>`;
  s.documents.forEach(d => {{
    html += `<li><strong>${{d.doc_type}}</strong> — <code>${{d.source_path}}</code></li>`;
  }});
  html += `</ul>`;
  if (s.findings.length > 0) {{
    html += `<p><strong>Findings (${{s.findings.length}}):</strong></p>`;
    html += `<table><tr><th>Field</th><th>Doc A Value</th><th>Doc B Value</th><th>Severity</th></tr>`;
    s.findings.forEach(f => {{
      html += `<tr><td>${{f.field}}</td><td>${{f.value_a || "N/A"}}</td><td>${{f.value_b || "N/A"}}</td><td>${{f.severity}}</td></tr>`;
    }});
    html += `</table>`;
  }}
  panel.innerHTML = html;
}}

render();
</script>
</body>
</html>"""

    dashboard_path = os.path.join(out_dir, "dashboard.html")
    with open(dashboard_path, "w", encoding="utf-8") as fh:
        fh.write(html)


def report(
    verdicts: list[ShipmentVerdict],
    docs: list[CanonicalDoc],
    out_dir: str,
    groups: list | None = None,
) -> dict:
    """Generate per-shipment reports and a results.json. Returns the results dict.

    Args:
        verdicts: Per-shipment verdicts from verification.
        docs: All canonical documents.
        out_dir: Output directory for reports and corrections.
        groups: Optional ShipmentGroup list. When provided, enables complete
                document lists for PASS verdicts with no findings.
    """
    doc_index = _build_doc_index(docs)

    # Build group_id -> doc_ids lookup from groups if provided
    group_doc_map: dict[str, list[str]] = {}
    if groups:
        for g in groups:
            group_doc_map[g.group_id] = list(g.doc_ids)

    # Create output directories
    os.makedirs(os.path.join(out_dir, "reports"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "corrections"), exist_ok=True)

    # Build results.json
    shipments = []
    passed = 0
    failed = 0

    for v in verdicts:
        if v.verdict == "PASS":
            passed += 1
        else:
            failed += 1

        # Collect all doc_ids in this group.  Prefer the authoritative groups
        # map when available; fall back to findings + suspects otherwise.
        # Uses sorted() for deterministic output order (no raw set iteration).
        if v.group_id in group_doc_map:
            group_doc_ids = sorted(group_doc_map[v.group_id])
        else:
            group_doc_ids = sorted(
                set(v.suspect_doc_ids)
                | {f.doc_a for f in v.findings}
                | {f.doc_b for f in v.findings}
            )

        group_docs = [doc_index[did] for did in group_doc_ids if did in doc_index]

        identifiers = _consensus_identifiers(v, doc_index)
        totals = _totals_from_docs(v, doc_index)

        entry = {
            "group_id": v.group_id,
            "verdict": v.verdict,
            "identifiers": identifiers,
            "totals": totals,
            "documents": [_doc_summary(d) for d in group_docs],
            "suspect_doc_ids": list(v.suspect_doc_ids),
            "findings": [_finding_as_dict(f) for f in v.findings],
        }
        shipments.append(entry)

        # Write markdown report
        _write_markdown_report(v.group_id, v, group_docs, out_dir, doc_index)

        # Write correction draft for FAIL shipments
        if v.verdict == "FAIL":
            _write_correction_draft(v.group_id, v, group_docs, doc_index, out_dir)

    results = {
        "summary": {
            "shipments": len(verdicts),
            "passed": passed,
            "failed": failed,
            "generated_by": "docverify",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "shipments": shipments,
    }

    # Write results.json
    results_path = os.path.join(out_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    # Generate self-contained dashboard.html (BUG-037)
    _generate_results_dashboard(results, out_dir)

    return results


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Reporting stage")
    parser.add_argument(
        "--in-dir", default="data/out",
        help="Input directory containing verdicts.json and canonical_docs.json (default: data/out)",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output directory (default: <in-dir>)",
    )
    args = parser.parse_args()

    base = args.in_dir
    out_dir = args.output or base
    verdicts_path = os.path.join(base, "verdicts.json")
    docs_path = os.path.join(base, "canonical_docs.json")

    if not os.path.exists(verdicts_path):
        print(f"Error: {verdicts_path} not found. Run verification first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(docs_path):
        print(f"Error: {docs_path} not found. Run extraction first.", file=sys.stderr)
        sys.exit(1)

    with open(verdicts_path, encoding="utf-8") as fh:
        verdicts_data = json.load(fh)
    with open(docs_path, encoding="utf-8") as fh:
        docs_data = json.load(fh)

    verdicts = [ShipmentVerdict.model_validate(v) for v in verdicts_data]
    docs = [CanonicalDoc.model_validate(d) for d in docs_data]

    results = report(verdicts, docs, out_dir)
    print(f"Reporting complete: {results['summary']['shipments']} shipments "
          f"({results['summary']['passed']} passed, {results['summary']['failed']} failed)")
    print(f"Output written to {out_dir}/")
