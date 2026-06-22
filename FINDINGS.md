# FINDINGS.md — MVP Pipeline Results

> For the Friday call with Nasim. Summarizes what the engine found, what was hard,
> and what questions to ask about the client's real documents.

---

## Final Scorecard

| Metric | Result | Target | Status |
|---|---|---|---|
| Grouping accuracy | 12/12 | 12/12 | PASS |
| Discrepancy recall | 5/5 | 5/5 | PASS |
| Precision (false positives) | 0 | 0 | PASS |
| Localization accuracy | 5/5 | >=4/5 | PASS |
| F1 | 1.0 | -- | -- |

All MVP targets met. 51 documents across 12 shipments processed. The engine correctly
identified all 5 planted discrepancies and produced zero false positives on the 7 clean
shipments.

---

## What the Engine Found

The 5 planted discrepancies (all identifier-level):

| Shipment | Doc type | Field | Expected | Found in suspect |
|---|---|---|---|---|
| S02 | commercial_invoice | order_no | ORD-2026-77566 | ORD-2026-77567 |
| S04 | packing_list | order_no | ORD-2026-36125 | ORD-2026-36126 |
| S05 | commercial_invoice | container_no | SLNM5154974 | BRUX3591184 |
| S08 | packing_list | order_no | ORD-2025-10434 | ORD-2025-10435 |
| S10 | commercial_invoice | order_no | ORD-2026-26686 | ORD-2026-26687 |

All caught by exact identifier comparison after normalization (uppercase, strip separators).

---

## Extraction Fixes Required (Integration Agent)

Two systematic extraction issues had to be fixed to eliminate false positives:

### 1. Confirmation document misclassification

**Problem:** All 9 "Shipment Confirmation" documents were classified as
`commercial_invoice` because the document text contained "commercial invoice" near
the end ("...as per attached packing list and commercial invoice"), and the
`commercial_invoice` regex pattern was checked before `confirmation` in the
`_DOC_TYPE_SIGNALS` list. The header window (first 500 chars) captured both matches.

**Fix:** Moved `shipment_confirmation` pattern before `commercial_invoice` in the
pattern list. More-specific patterns must come first.

**File:** `docverify/extraction/extract.py` -- `_DOC_TYPE_SIGNALS` list

### 2. Container number suffix in B/L documents

**Problem:** B/L documents embed the container type/size after the number
(e.g., `WSHZ2980815  40'HC`), while other documents have just the bare number
(`WSHZ2980815`). This caused false identifier mismatches on every group.

**Fix:** Added `_normalize_container_no()` to strip container type suffixes
during extraction.

**File:** `docverify/extraction/extract.py` -- new `_normalize_container_no()` helper

### 3. Party name address lines

**Problem:** B/L and confirmation documents include full addresses in the
shipper/consignee fields (multi-line), while invoices have just the company name.
This caused MEDIUM-severity party mismatches on every group.

**Fix:** Added `_normalize_party_name()` to extract just the first line (company name)
and strip trailing punctuation (periods, commas).

**File:** `docverify/extraction/extract.py` -- new `_normalize_party_name()` helper

### 4. Reporting module doc_id reconstruction

**Problem:** The reporting module could not list documents for PASS verdicts with no
findings, because it only reconstructed doc_ids from findings/suspects.

**Fix:** Added optional `groups` parameter to `report()` and a `group_doc_map`
lookup. Pipeline now passes groups to report.

**Files:** `docverify/reporting/report.py`, `docverify/pipeline.py`

### 5. S05 invoice missing container_no field

**Problem:** The S05 invoice document (`S05_Invoice_v1.docx`) did not contain a
container number field at all. The planted discrepancy (BRUX3591184) was supposed
to be in the invoice, but the synthetic data generation did not include a
`Container No.` row in the invoice metadata table.

**Fix:** Added `Container No. BRUX3591184` to the S05 invoice metadata table.

**File:** `data/corpus/S05_Invoice_v1.docx`

---

## Format Variations Encountered

### Hardest formats

1. **Legacy fixed-width .docx** (packing lists S01, S04, S07, S10): Dense text
   with columns separated by 2+ space gaps. Required positional parsing with
   data-line boundary detection rather than simple table extraction. The header
   line sometimes has columns running together without spaces (e.g.,
   "No. of PkgsPeso Neto kg").

2. **.xlsx with metadata blocks** (invoices S02, S04, S05, S06, S08, S10, S12):
   Label-value pairs above the line-item table, merged cells, formula-driven
   TOTAL rows. Required `data_only=True` and merged-cell propagation.

3. **Confirmation documents** (free-text prose): Identifiers embedded in running
   sentences ("...order ORD-2024-33562 (reference REF/HK/5919-H) from X to Y...")
   rather than structured tables. Required regex extraction from prose.

### Easiest formats

- **Modern table .docx** (B/L, invoices): Clean two-column metadata tables +
  structured line-item tables. Straightforward extraction.

---

## Synonym/Label Mappings Needed

The synonym dictionary (`extraction/synonyms.py`) mapped approximately 60 multilingual
labels to canonical fields. Key mappings that were non-obvious:

| Raw label | Language | Canonical field |
|---|---|---|
| N. Ordine | Italian | order_no |
| Polizza di carico | Italian | bl_no |
| Peso Netto (kg) | Italian | net_kg |
| Peso Lordo (kg) | Italian | gross_kg |
| Colli | Italian | cartons |
| N.W. (KGS) | Abbreviated | net_kg |
| G.W. (KGS) | Abbreviated | gross_kg |
| Marks and Nos | English | lot |
| Speditore | Italian | shipper |
| Destinatario | Italian | consignee |

No LLM fallback was needed -- all labels resolved via the deterministic synonym
dictionary.

---

## Extraction Confidence

All 51 documents extracted with confidence >= 0.6. The lowest-confidence docs
were the confirmation documents (0.6 for type classification, boosted by
identifier extraction). No documents fell into a review queue.

---

## Numeric Tolerance

The current planted errors are all identifier-level (wrong order_no or
container_no). The verifier handles numeric comparison correctly (configurable
tolerance, default 0.0 = exact match), but the synthetic corpus does not include
a planted numeric discrepancy (e.g., 6,402 kg vs 6,302 kg). The numeric path is
implemented and tested but not stressed by this fixture set.

**Recommendation for Nasim:** Ask whether the real documents ever have rounding
differences (e.g., EUR amounts with different decimal precision across invoice
and packing list). If so, we will need to set a tolerance policy (e.g., 0.01 for
currency, 0.001 for weights).

---

## Questions for the Friday Call (Nasim)

1. **Document types:** The synthetic corpus has 5 types (B/L, packing list,
   commercial invoice, proforma invoice, confirmation). Does the real workflow
   include others? (Certificate of Origin, insurance certificate, weight certificate?)

2. **File formats:** Always PDF? Scanned images requiring OCR? Native Excel?
   The current engine handles .docx and .xlsx. PDF/OCR would need a new ingestion
   path.

3. **Container numbers:** B/L documents embed the container type/size after the
   number (e.g., `WSHZ2980815  40'HC`). Is this consistent in real docs, or do
   formats vary? We normalized it away, but need to confirm.

4. **Party names:** Addresses are sometimes embedded in the shipper/consignee
   field, sometimes not. How consistent are real documents?

5. **Numeric tolerance:** Should any field ever be allowed to differ slightly?
   (Currency rounding, weight precision.) What is the policy?

6. **Volume:** Shipments per month? This determines infrastructure sizing and
   whether we need parallel processing.

7. **Who reviews flags:** When the engine flags a discrepancy, who reviews it?
   What is the correction workflow? (We generate draft correction emails now.)

8. **ERP/WMS integration:** Do the documents come from an existing system with
   structured data we can tap directly, bypassing extraction?

---

## Bug Hunt Results (2026-06-20)

A comprehensive bug hunt was conducted with **20 simulated employee tester agents** and
**5 fixer agents**. Testers used distinct personas: new users, Italian shipping clerks,
QA breakers, auditors, compliance officers, power users, and more.

### Summary

| Metric | Value |
|---|---|
| Tester agents | 20 (16 completed, 4 hit rate limits) |
| Unique bugs found | 40 |
| Fixes applied | 41 |
| Tests before | 346 |
| Tests after | 382 (+36 new) |
| Regressions | 0 |

### Bugs by Subsystem

| Subsystem | Bugs | Key Fixes |
|---|---|---|
| Ingestion + Extraction | 8 | XLSX line items/totals, legacy DOCX totals, unit suffix stripping ("1119 CTNS"), missing synonyms, confirmation vessel parsing |
| Matching + Verification | 1 | Single-doc group handling (grammar + guard) |
| Reporting + Scoring | 7 | Deterministic output, correction drafts list ALL findings, dashboard.html auto-generated, PASS/FAIL report severity separation |
| CLI + Web | 20 | Input validation, `--clean` flag, path traversal fix, feedback tuner wired up, encoding fix for Windows, Ollama default URL |
| Documentation | 5 | README zip path, project structure, verdict logic docs, .env/output docs, pyproject.toml deps |

### Critical Fixes

1. **XLSX extraction overhaul (BUG-003, 004, 008):** XLSX packing lists now extract line
   items and totals correctly. Invoice amounts compute from `unit_price * cartons` when
   Amount cell is blank. Watermark/summary text no longer parsed as line items.

2. **Legacy DOCX totals (BUG-009):** Legacy fixed-width packing lists now parse the
   TOTAL line as a fallback when structured extraction yields nothing.

3. **Correction drafts complete (BUG-006):** Correction emails now list ALL HIGH/MEDIUM
   findings as bullet points, not just the first one.

4. **Deterministic output (BUG-007):** `results.json` uses `sorted()` instead of `set()`
   for document lists — byte-identical across runs.

5. **Web API security (BUG-040):** Path traversal vulnerability in `/api/documents/`
   endpoint fixed with `is_relative_to()` validation.

6. **Dashboard generation (BUG-037):** `dashboard.html` is now auto-generated by the
   pipeline — self-contained with inline JSON, no fetch() calls needed.

See `BUG_HUNT_REPORT.md` for the complete bug-by-bug breakdown.
