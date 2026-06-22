# QA Report — docverify Engine MVP

**Agent:** 92 (QA / Test Engineer)
**Date:** 2026-06-17
**Verdict:** **GO for Friday demo**

---

## 1. Scorecard (Full Corpus — 51 documents, 12 shipments)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Discrepancy recall | 5/5 | 5/5 (100%) | PASS |
| False positives (clean shipments) | 0 | 0 | PASS |
| Localization accuracy | >=4/5 | 5/5 (100%) | PASS |
| Grouping accuracy | 12/12 | 12/12 (100%) | PASS |
| Precision | -- | 1.0 | -- |
| F1 | -- | 1.0 | -- |

**All four MVP targets: PASS**

---

## 2. Per-Shipment Verdict (Confusion Table)

| Ship | Planted Error | Expected | Predicted | Correct |
|------|--------------|----------|-----------|---------|
| S01  | no           | PASS     | PASS      | OK      |
| S02  | YES          | FAIL     | FAIL      | OK      |
| S03  | no           | PASS     | PASS      | OK      |
| S04  | YES          | FAIL     | FAIL      | OK      |
| S05  | YES          | FAIL     | FAIL      | OK      |
| S06  | no           | PASS     | PASS      | OK      |
| S07  | no           | PASS     | PASS      | OK      |
| S08  | YES          | FAIL     | FAIL      | OK      |
| S09  | no           | PASS     | PASS      | OK      |
| S10  | YES          | FAIL     | FAIL      | OK      |
| S11  | no           | PASS     | PASS      | OK      |
| S12  | no           | PASS     | PASS      | OK      |

---

## 3. Per-Error Localization

| Shipment | Error Location | Expected Field | Found Field | Correct |
|----------|---------------|----------------|-------------|---------|
| S02      | invoice       | order_no       | order_no    | YES     |
| S04      | packing_list  | order_no       | order_no    | YES     |
| S05      | invoice       | container_no   | container_no| YES     |
| S08      | packing_list  | order_no       | order_no    | YES     |
| S10      | invoice       | order_no       | order_no    | YES     |

---

## 4. Edge-Case Test Matrix

99 edge-case tests added in `tests/test_edge_cases.py`. All pass.

| Category | Tests | Status | Notes |
|----------|-------|--------|-------|
| Swapped net/gross columns | 2 | PASS | Both 2-doc and 3-doc (majority rules) scenarios |
| Thousands separators & currency | 18 | PASS | US, EU, space-separated, currency symbols (EUR, USD, GBP) |
| Numeric error detection (6402 vs 6302) | 4 | PASS | Detection, suspect identification, tolerance suppress/catch |
| Multilingual labels (EN/IT/ES) | 42 | PASS | net_kg (11 variants), gross_kg (9), cartons (7), identifiers/parties (11), case insensitivity, unrecognized |
| Legacy vs modern docx | 3 | PASS | Real fixtures: legacy packing list, modern invoice, synthetic modern |
| xlsx metadata + formulas | 3 | PASS | Metadata block extraction, formula TOTAL row, real fixture |
| Missing/null fields | 3 | PASS | No false discrepancies on null fields, partial overlap |
| 2-doc ambiguity | 2 | PASS | Both docs flagged as suspects in disagreement; agreement passes |
| Pipeline determinism | 2 | PASS | Two runs produce identical results; scoring is deterministic |
| Corrupt/empty files | 7 | PASS | Empty docx, garbage bytes, corrupt xlsx, non-doc files, mixed valid+invalid, empty dir, nonexistent dir |
| Unknown doc type | 2 | PASS | Classified as unknown; fields still extracted |
| Identifier normalization | 5 | PASS | Hyphens, case, slashes, dots, container numbers |
| End-to-end edge cases | 3 | PASS | Numeric mismatch in pipeline, clean shipment passes, corrupt file in corpus |
| Matching edge cases | 5 | PASS | No identifiers (singletons), BL/container linking, fuzzy threshold, deterministic group IDs |

---

## 5. Integration Test Suite

14 integration tests added in `tests/test_integration.py`. All pass.

| Test | Status | Description |
|------|--------|-------------|
| Pipeline runs without error | PASS | Mixed docx+xlsx corpus, 4 docs |
| All stage artifacts written | PASS | raw_docs, canonical_docs, groups, verdicts, results JSON |
| Correct doc count | PASS | 4 docs ingested and extracted |
| Two groups formed | PASS | Documents correctly clustered |
| Clean shipment passes | PASS | S01 (consistent docs) gets PASS |
| Broken shipment fails | PASS | S02 (altered order_no) gets FAIL |
| Suspect doc identified | PASS | xlsx invoice correctly flagged as suspect |
| Scoring matches answer key | PASS | recall 1/1, FP 0, grouping 2/2 |
| Scoring individual metrics | PASS | All per-metric checks correct |
| Scoring confusion table | PASS | S01=PASS(correct), S02=FAIL(correct) |
| Scorecard written to disk | PASS | JSON serializable and reloadable |
| Reports written | PASS | 2 markdown reports generated |
| Correction draft for FAIL | PASS | Correction email mentions altered order |
| Results JSON structure | PASS | summary + shipments with expected shape |

---

## 6. Full Suite Summary

| Suite | Tests | Status |
|-------|-------|--------|
| Existing (pre-QA) | 233 | ALL PASS |
| Edge-case (new) | 99 | ALL PASS |
| Integration (new) | 14 | ALL PASS |
| **Total (pre-bug-hunt)** | **346** | **ALL PASS** |
| Bug hunt fixes (2026-06-20) | +36 | ALL PASS |
| **Total (current)** | **382** | **ALL PASS** |

---

## 7. Bugs Found

**None at time of initial QA (2026-06-17).** All edge cases behaved as expected.

**40 bugs found during Bug Hunt (2026-06-20)** — see Section 12 below.

---

## 8. Observations (Not Bugs)

1. **xlsx doc type classification**: xlsx invoices without explicit "Commercial Invoice" text in cells may be classified as `unknown` rather than `commercial_invoice`. The extraction still works correctly (fields are extracted), but the doc_type metadata may be less precise for xlsx files. This does not affect verification accuracy since matching uses identifier content, not doc_type.

2. **Line-item cross-doc comparison**: When one document has line items and another does not (e.g., a BL vs an invoice), the line items show as "only found in one document" at LOW severity. This is correct behavior (informational, not a failure), but could be noisy in reports. Consider filtering LOW-severity findings from the default report view.

3. **Scoring harness targets**: The `overall_pass` field in the scorecard requires `recall_5_of_5` and `grouping_12_of_12`, which are hard-coded for the full 12-shipment corpus. This is correct for the production scorer but means mini-corpus integration tests cannot achieve `overall_pass=True`.

---

## 9. GO/NO-GO Verdict

### **GO for Friday demo**

**Justification:**

- All 4 MVP targets are met with perfect scores (5/5 recall, 0 FP, 5/5 localization, 12/12 grouping)
- 346 tests pass including 113 new edge-case and integration tests
- The engine handles real-world document messiness: multilingual labels, number format variations, corrupt files, swapped columns
- Pipeline is deterministic (same input produces same output)
- No bugs found; no product code was modified to force green
- The engine correctly identifies which document contains each planted error and which field is mismatched

**Risk areas for real-world deployment (not blocking Friday demo):**

- xlsx doc_type classification could be improved with content-based heuristics
- LOW-severity line-item findings may need filtering for production reports
- Real client documents may have format variations not covered by the synthetic corpus (recommend collecting samples during the Friday call)

---

## 12. Bug Hunt Report (2026-06-20)

### Methodology

20 simulated employee tester agents with distinct personas tested the MVP practically:
new users, Italian shipping clerks, QA breakers, auditors, compliance officers, power
users, data analysts, document controllers, and more. 5 fixer agents then patched bugs
by subsystem (ingestion+extraction, matching+verification, reporting+scoring, cli+web,
documentation).

### Results

| Metric | Value |
|---|---|
| Tester agents launched | 20 (16 completed, 4 hit 429 rate limits) |
| Unique bugs found | 40 |
| Fixes applied | 41 |
| Tests before | 346 |
| Tests after | 382 (+36 new) |
| Regressions | 0 |
| Pipeline after fixes | 51 docs → 12 groups → 7 PASS / 5 FAIL (correct) |

### Bugs by Subsystem

**Ingestion + Extraction (8 bugs):**
- BUG-003: XLSX invoice amounts/totals null → fallback computation from line items
- BUG-004: XLSX packing lists extract zero line items → header row scoring rewrite
- BUG-008: XLSX watermark text parsed as line items → skip 'total'/'specimen' rows
- BUG-009: Legacy DOCX packing lists missing totals → fallback to legacy TOTAL parser
- BUG-010: BL cartons missed ("1119 CTNS") → unit suffix stripping in parse_number
- BUG-011: Confirmation docs append 'voyage' to vessel → post-processing strip
- BUG-012: Empty docs produce duplicate doc_ids → source_path in content hash
- BUG-025: Missing synonym 'Qty (ctns)' → added to dictionary

**Matching + Verification (1 bug):**
- BUG-036: Single-doc groups show misleading "All fields agree" → proper guard message

**Reporting + Scoring (7 bugs):**
- BUG-002: results.json omits 14 documents → uses authoritative group_doc_map
- BUG-005: "per the other 0 documents" → fixed n_other calculation
- BUG-006: Correction drafts only list first finding → iterates ALL HIGH/MEDIUM
- BUG-007: Non-deterministic document order → sorted() instead of set()
- BUG-029: PASS reports suppress low-severity findings → "All critical fields agree" + table
- BUG-030: LOW noise drowns real errors in FAIL reports → severity-separated sections
- BUG-037: No dashboard.html generated → auto-generated self-contained HTML

**CLI + Web (20 bugs):**
- BUG-001: Agent simulator crashes when rng_seed is None
- BUG-013: Web API drops numeric_tolerance=0.0 via falsy check
- BUG-014: Frontend config tolerance/LLM not wired to pipeline
- BUG-015: Verification crashes with raw traceback on missing files
- BUG-016: Ingestion exits 0 on nonexistent corpus path
- BUG-017: Pipeline creates empty output dir even when corpus fails
- BUG-018: Stale artifacts not cleaned → new --clean flag
- BUG-019: Broken test fixture in test_malformed_docs.py
- BUG-020: Matching/verify/report CLIs ignore --help and args
- BUG-026: --email-inbox + --corpus together causes crash
- BUG-027: --num-emails accepts negative values
- BUG-028: --numeric-tolerance accepts NaN/inf/negative
- BUG-031: Dry-run still creates files in generated/mixed modes
- BUG-032: Error injection feature is dead code → wired up
- BUG-033: Web API has no input validation
- BUG-034: Feedback tuner overrides never loaded by pipeline
- BUG-035: Em-dash in help string causes encoding error on Windows
- BUG-038: Ollama default URL hardcoded to LAN IP
- BUG-039: WARNING log shows full stack trace for ingest failures
- BUG-040: Path traversal in /api/documents/{filename} → is_relative_to() check

**Documentation (5 fixes):**
- BUG-021: README zip path wrong + added Windows equivalents
- BUG-022: Project structure missing 5 subdirectories
- BUG-023: No PASS/FAIL verdict logic or severity docs
- BUG-024: No docs for .env, output files, prerequisites, dashboard
- Extra: pyproject.toml missing dependencies (python-dotenv, requests, optional groups)

### Post-Fix Verification

All 382 tests pass. Pipeline runs cleanly end-to-end. Key artifacts verified:
- results.json includes all 51 documents (BUG-002 confirmed fixed)
- No "per the other 0 documents" anywhere (BUG-005 confirmed fixed)
- Correction drafts list all discrepancies (BUG-006 confirmed fixed)
- Deterministic output across runs (BUG-007 confirmed fixed)
- PASS/FAIL reports properly separate severity levels (BUG-029/030 confirmed fixed)
- dashboard.html generated and self-contained (BUG-037 confirmed fixed)
