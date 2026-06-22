# DocVerify — Technical Documentation

**Phase 1 MVP: Shipping Document Cross-Reference Verification Engine**

---

## 1. What This System Does

DocVerify automates the cross-checking of shipping documents for a food import/export
logistics operation (pasta shipped in containers, Italy to Lebanon/UAE/HK).

Every shipment generates a set of legally binding documents (Bill of Lading, Packing List,
Commercial Invoice, Pro Forma Invoice, Shipment Confirmation). These must agree on every
shared field. A single mismatch — a wrong container number, a transposed order number,
6,302 kg instead of 6,402 kg — causes port delays, fines, and lost clients.

Today one employee spends ~80% of his time manually cross-checking these documents.
DocVerify replaces that with an automated pipeline.

### What it does NOT do (Phase 1 scope)

- No document generation (Phase 3)
- No email/Outlook ingestion (Phase 3)
- No interactive dashboard UI (Phase 2 — `results.json` is the feed)
- No auto-sending correction emails (Phase 3 — drafts only)

---

## 2. Architecture

### Pipeline (5 stages, parallel where possible)

```
Raw files (.docx / .xlsx)
        |
        v
[A] Ingestion       →  RawDoc (text + tables + content hash)
        |
        v
[B] Extraction      →  CanonicalDoc (typed fields, multilingual labels mapped)
        |
        v
[C] Matching        →  ShipmentGroup (clusters by identifier overlap)
        |
        v
[D] Verification    →  ShipmentVerdict (PASS/FAIL, findings, suspect docs)
        |
        v
[E] Reporting       →  results.json + per-shipment reports + correction drafts
        |
        v
[Scoring]           →  scorecard.json (compared against answer_key.json)
```

### Subagent responsibilities

| Stage | Module | What it does |
|---|---|---|
| A — Ingestion | `ingestion/ingest.py` | Reads .docx (modern tables + legacy fixed-width) and .xlsx (metadata blocks + formula totals). Produces `RawDoc` with raw text, tables, and content-hash `doc_id`. |
| B — Extraction | `extraction/extract.py` | Maps multilingual field labels to canonical schema via deterministic synonym dictionary (100+ mappings, EN/IT/ES). Classifies doc_type from content. Optional Gemini LLM fallback (off by default). |
| C — Matching | `matching/match.py` | Union-find clustering by identifier overlap (B/L no, order no, container no, reference). Fuzzy matching as secondary signal only. Never uses filenames. |
| D — Verification | `verification/verify.py` | Compares every shared field across a shipment group. Identifiers: exact match (HIGH). Weights: numeric with configurable tolerance (HIGH). Parties: normalized string (MEDIUM). Logistics: informational (LOW). Majority-vote outlier detection. |
| E — Reporting | `reporting/report.py` | Generates per-shipment markdown reports, machine-readable `results.json`, and correction-request email drafts (draft only). |
| Scoring | `scoring/score.py` | Compares `results.json` against `answer_key.json`. Computes recall, precision, F1, localization accuracy, grouping accuracy. |

---

## 3. Canonical Data Schema

All extractors emit records validated against this Pydantic v2 model. Defined in
`schemas/models.py` and `docverify/docverify/schemas/models.py`.

```python
class CanonicalDoc(BaseModel):
    doc_id: str                        # sha256 of normalized content, NOT filename
    source_path: str                   # original path, for human reports only
    doc_type: DocType                  # bill_of_lading | packing_list | commercial_invoice |
                                       # proforma_invoice | confirmation | unknown
    source_format: SourceFormat        # docx | xlsx
    identifiers: Identifiers           # order_no, bl_no, reference, container_no, seal_no
    parties: Parties                   # shipper, consignee
    logistics: Logistics               # vessel, voyage, pol, pod, ship_date
    line_items: list[LineItem]         # description, lot, cartons, net_kg, gross_kg, etc.
    totals: Totals                     # cartons, net_kg, gross_kg, value, currency
    extraction_confidence: float       # 0.0 to 1.0
    raw_field_labels: dict[str, str]   # canonical field -> original label seen
```

### Stage I/O models

| Model | Producer | Consumer |
|---|---|---|
| `RawDoc` | Ingestion | Extraction |
| `CanonicalDoc` | Extraction | Matching, Verification, Reporting |
| `ShipmentGroup` | Matching | Verification |
| `ShipmentVerdict` | Verification | Reporting |
| `Finding` | Verification | Reporting |

---

## 4. Test Corpus

`synthetic_shipping_docs.zip` — 51 synthetic shipping documents across 12 shipments.

### Format breakdown

| Format | Count | Description |
|---|---|---|
| .docx (modern) | ~25 | Clean Word tables |
| .docx (legacy) | ~16 | Dense fixed-width text dumps |
| .xlsx | 10 | Spreadsheets with metadata blocks + formula TOTAL rows |

### Doc types per shipment

| Doc Type | Always present? |
|---|---|
| Bill of Lading | Yes |
| Packing List | Yes |
| Commercial Invoice | Yes |
| Pro Forma Invoice | ~7 shipments |
| Shipment Confirmation | ~9 shipments |

### Field label variation (multilingual)

| Canonical field | Label variants found in corpus |
|---|---|
| net_kg | "Net Weight (kg)", "Peso Netto (kg)", "N.W. (KGS)", "Peso Neto kg" |
| gross_kg | "Gross Weight (kg)", "Peso Lordo (kg)", "G.W. (KGS)", "Peso Bruto kg" |
| cartons | "Cartons", "Colli", "Cartons/Cases", "No. of Cartons", "Cajas", "CTNS" |
| order_no | "Order No", "Order Number", "Ordine", "N. Ordine", "PO", "P/O No" |
| bl_no | "B/L No", "Bill of Lading No", "BL Number", "Polizza di carico" |
| container_no | "Container No", "Container", "Container/Seal", "Contenitore" |

### Planted discrepancies

5 of 12 shipments have exactly one planted error. 7 are clean.

| Shipment | Error location | Error |
|---|---|---|
| S02 | invoice (.xlsx) | order_no: ORD-2026-77566 -> ORD-2026-77567 |
| S04 | packing_list (legacy .docx) | order_no: ORD-2026-36125 -> ORD-2026-36126 |
| S05 | invoice (.docx) | container_no: SLNM5154974 -> BRUX3591184 |
| S08 | packing_list (.xlsx) | order_no: ORD-2025-10434 -> ORD-2025-10435 |
| S10 | invoice (.xlsx) | order_no: ORD-2026-26686 -> ORD-2026-26687 |

**Note:** All current planted errors are identifier-level. The real-world failure mode
is subtle numeric mismatches (e.g. 6,402 vs 6,302 kg). The verifier handles numeric
comparison with configurable tolerance, and the test suite covers this, but the current
fixtures don't stress it.

---

## 5. Scoring & Results

### Targets vs actual

| Metric | Target | Actual | Status |
|---|---|---|---|
| Grouping accuracy | 12/12 | 12/12 | PASS |
| Discrepancy recall | 5/5 | 5/5 | PASS |
| False positives | 0 | 0 | PASS |
| Localization accuracy | >=4/5 | 5/5 | PASS |
| F1 score | — | 1.0 | PASS |

### Confusion table

| Ship | Planted | Expected | Predicted | Correct |
|---|---|---|---|---|
| S01 | no | PASS | PASS | OK |
| S02 | YES | FAIL | FAIL | OK |
| S03 | no | PASS | PASS | OK |
| S04 | YES | FAIL | FAIL | OK |
| S05 | YES | FAIL | FAIL | OK |
| S06 | no | PASS | PASS | OK |
| S07 | no | PASS | PASS | OK |
| S08 | YES | FAIL | FAIL | OK |
| S09 | no | PASS | PASS | OK |
| S10 | YES | FAIL | FAIL | OK |
| S11 | no | PASS | PASS | OK |
| S12 | no | PASS | PASS | OK |

---

## 6. Test Suite

**382 tests total**, all passing (346 original + 36 from bug hunt fixes).

| Category | Count | What it covers |
|---|---|---|
| Unit — utils | 52 | Number parsing (US/EU/currency), identifier normalization, content hashing |
| Unit — ingestion | 25 | Modern docx, legacy docx, xlsx, merged cells, formula rows, content hash stability |
| Unit — extraction | 111 | Synonym dictionary (all EN/IT/ES variants), doc_type classification, KV extraction, offline operation |
| Unit — matching | 11 | Union-find clustering, corrupted identifier handling, fuzzy fallback, determinism |
| Unit — verification | 16 | Clean groups, identifier mismatches, numeric tolerance, majority vote, ambiguous 2-doc cases |
| Unit — reporting | 11 | results.json shape, markdown reports, correction drafts, summary counts |
| Edge cases | 99 | Swapped columns, thousands separators, numeric errors, multilingual labels, corrupt files, determinism |
| Integration | 14 | End-to-end pipeline on mini corpus, scoring, report generation |
| Pipeline | 7 | Full pipeline smoke test, scoring harness |

---

## 7. How to Run

```sh
cd "PASTA PROJ/docverify"

# Setup
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Full pipeline
python -m docverify.pipeline --corpus data/corpus --out data/out
python -m docverify.pipeline --corpus data/corpus --out data/out --clean  # wipe output dir first
python -m docverify.pipeline --corpus data/corpus --out data/out --numeric-tolerance 0.01

# Score
python -m docverify.scoring.score --results data/out/results.json --answer-key ../answer_key.json

# Tests
pytest -q

# Individual stages
python -m docverify.ingestion.ingest data/corpus
python -m docverify.extraction.extract
python -m docverify.matching.match
python -m docverify.verification.verify
python -m docverify.reporting.report

# Dashboard (requires local server for fetch)
cd data/out && python -m http.server 8080
# Open http://localhost:8080/dashboard.html
```

---

## 8. File Structure

```
docverify/
├── README.md
├── FINDINGS.md                        # Scorecard + extraction fixes + questions for Nasim
├── BRIEF.md                           # Living project brief
├── SECURITY_AUDIT.md                  # Privacy audit (PASS)
├── SIMPLICITY_REVIEW.md               # Code review
├── QA_REPORT.md                       # GO for Friday demo + bug hunt results
├── BUG_HUNT_REPORT.md                 # Full 40-bug report (20 testers + 5 fixers)
├── CONTRACT_CHANGE_REQUESTS.md        # Empty (no schema changes needed)
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
├── docverify/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── models.py                  # Canonical Pydantic models (13 models)
│   ├── utils.py                       # Shared helpers (hash, parse, normalize)
│   ├── ingestion/
│   │   └── ingest.py                  # .docx + .xlsx normalizer
│   ├── extraction/
│   │   ├── extract.py                 # Deterministic synonym extractor
│   │   ├── synonyms.py                # 100+ multilingual label mappings
│   │   └── llm_fallback.py            # Optional Gemini fallback
│   ├── matching/
│   │   └── match.py                   # Union-find clustering
│   ├── verification/
│   │   └── verify.py                  # Cross-field comparison + majority vote
│   ├── reporting/
│   │   └── report.py                  # Reports + results.json + correction drafts
│   ├── scoring/
│   │   └── score.py                   # Answer key comparison harness
│   └── pipeline.py                    # End-to-end orchestrator CLI
├── data/                              # Gitignored
│   ├── corpus/                        # 51 unzipped test documents
│   └── out/
│       ├── raw_docs.json              # Stage A output
│       ├── canonical_docs.json        # Stage B output
│       ├── groups.json                # Stage C output
│       ├── verdicts.json              # Stage D output
│       ├── results.json               # Stage E output (dashboard feed)
│       ├── scorecard.json             # Scoring output
│       ├── dashboard.html             # Interactive visualization
│       ├── reports/*.md               # Per-shipment human reports
│       └── corrections/*.txt          # Correction request drafts
└── tests/
    ├── fixtures/                      # Tiny hand-made sample docs
    ├── conftest.py                    # Shared pytest fixtures
    ├── test_utils.py
    ├── test_ingestion.py
    ├── test_extraction.py
    ├── test_matching.py
    ├── test_verification.py
    ├── test_reporting.py
    ├── test_edge_cases.py
    ├── test_integration.py
    ├── test_pipeline.py
    ├── test_email.py                  # Email, agent, generator, feedback tests
    ├── test_llm_router.py             # LLM router + Ollama client tests
    └── test_malformed_docs.py         # Bug hunt: corrupt/empty document tests
```

---

## 9. Data Privacy

- Raw documents go ONLY to the Anthropic API (zero-retention / no-train) or local models
- Never a consumer AI interface, never an endpoint that trains on the data
- The only permitted outbound call: optional Gemini fallback (`use_llm=True` + `GEMINI_API_KEY`)
- Default pipeline runs fully offline (`use_llm=False`)
- `data/` and `.env` are gitignored
- No document contents logged at INFO level
- No secrets hardcoded or printed

---

## 10. What's Next

### Phase 2 — Interactive Dashboard
- ~~Web UI for reviewing flagged shipments~~ **DONE (BUG-037).** `dashboard.html` is
  auto-generated by the pipeline — self-contained with inline JSON, filterable table,
  click-to-expand details. No server needed.
- `results.json` feed is already built
- Human-in-the-loop workflow for approving corrections

### Phase 3 — Production Integration
- Email/Outlook ingestion (plug-in source for the pipeline)
- Auto-sending correction emails (drafts already generated)
- Document generation (auto-filling packing lists/invoices)
- ERP/WMS integration for structured data
- Encryption at rest, RBAC, audit logging

---

## 11. Questions for Client (Nasim)

1. What are all the actual document types? (COO, insurance cert?)
2. What formats do real documents arrive in? (PDF? Scanned? Native Excel?)
3. What is the monthly shipment volume?
4. Which fields are legally critical vs nice-to-check?
5. Should any numeric field ever be allowed to differ? (Tolerance policy?)
6. Who reviews and approves flagged corrections?
7. What existing systems (ERP/WMS) do docs originate from?
8. Authorization to receive real (redacted first) sample documents.
