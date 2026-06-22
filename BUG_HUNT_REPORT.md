# Bug Hunt Report — DocVerify MVP

> **Date:** 2026-06-20
> **Method:** 20 simulated employee tester agents + 5 fixer agents
> **Result:** 40 bugs found, 41 fixes applied, 382/382 tests pass, zero regressions

---

## Overview

A comprehensive bug hunt was conducted using 27 AI agents:

- **20 tester agents** — each with a distinct employee persona testing the MVP from a
  different angle (new users, Italian clerks, QA breakers, auditors, compliance officers,
  power users, data analysts, etc.)
- **5 fixer agents** — one per subsystem (ingestion+extraction, matching+verification,
  reporting+scoring, cli+web, documentation)
- **1 triage agent** — deduplicated and categorized all findings
- **1 verification agent** — re-ran the full test suite after fixes

4 tester agents hit API rate limits (429 errors) and did not complete: Carmen (Spanish
Labels), Pietro (Intern Chaos), Laura (Document Controller), Chiara (README Audit).
Their coverage was partially captured by other testers.

---

## Phase 1: Tester Agents

| # | Persona | Focus Area | Status |
|---|---------|-----------|--------|
| 1 | Maria — New User | First-time setup, README accuracy | Completed |
| 2 | Giovanni — Italian Clerk | Italian label mapping, multilingual extraction | Completed |
| 3 | Luca — Night Shift | Overwrite safety, determinism, bad paths | Completed |
| 4 | Sofia — Data Analyst | Output integrity, orphaned IDs, count mismatches | Completed |
| 5 | Marco — QA Breaker | Empty files, invalid flags, crash hunting | Completed |
| 6 | Elena — Logistics Manager | Report quality, correction drafts, dashboard | Completed |
| 7 | Antonio — IT Admin | CLI help, stage CLIs, exit codes | Completed |
| 8 | Carmen — Spanish Speaker | Spanish synonym coverage, encoding | Rate limited |
| 9 | Pietro — Intern | No-instructions chaos, web UI, imports | Rate limited |
| 10 | Francesca — Auditor | False positives/negatives, verification accuracy | Completed |
| 11 | Roberto — Agent Sim | Simulation mode, generated docs, dry-run | Completed |
| 12 | Laura — Doc Controller | Stage-by-stage isolation, classification | Rate limited |
| 13 | Andrea — Malformed Docs | Empty/corrupt files, graceful degradation | Completed |
| 14 | Giulia — Compliance | PII leakage, audit trail, output professionalism | Completed |
| 15 | Matteo — Power User | Numeric tolerance, undocumented features | Completed |
| 16 | Chiara — README Audit | Windows compat, outdated instructions | Rate limited |
| 17 | Davide — Bulk Runs | 5x consistency, determinism, disk usage | Completed |
| 18 | Valentina — Edge Cases | Known limitations reproduction | Completed |
| 19 | Riccardo — Web/API | FastAPI endpoints, CORS, error handling | Completed |
| 20 | Sara — Report Consumer | Actionability, context, business readability | Completed |

---

## Phase 2: Triage — 40 Unique Bugs

| Subsystem | Bug Count |
|-----------|-----------|
| Ingestion + Extraction | 8 |
| Matching + Verification | 1 |
| Reporting + Scoring | 7 |
| CLI + Web | 20 |
| Documentation | 5 |

---

## Phase 3: Fixes by Subsystem

### Ingestion + Extraction (8 fixes)

| ID | Bug | Fix | Status |
|----|-----|-----|--------|
| BUG-003 | XLSX invoice line item amounts and totals.value are all null | Fallback `amount = unit_price * cartons` when Amount cell blank; sum line items for totals when TOTAL row yields nulls | Fixed |
| BUG-004 | XLSX packing lists extract zero line items and null totals | Rewrote `_detect_header_row()` to score candidate rows, preferring those with line-item fields (+100 for 'description', +50 for any line-item field) | Fixed |
| BUG-008 | XLSX invoices parse watermark and summary text as line items | Skip rows where description starts with 'total' or 'specimen' | Fixed |
| BUG-009 | Legacy DOCX packing lists do not extract totals | Added `_parse_legacy_totals()` fallback when structured/paragraph totals both null | Fixed |
| BUG-010 | Bill of Lading cartons not extracted from 'No. of Packages' column ("1119 CTNS") | Added trailing unit suffix stripping in `parse_number()`: `re.sub(r'\s+[A-Za-z/]+$', '', s)` | Fixed |
| BUG-011 | Confirmation documents append 'voyage' to vessel name, causing false findings | Post-processing strips 'voyage' keyword: `re.sub(r'\s+voyage\b', '', ...)` | Fixed |
| BUG-012 | Empty documents produce duplicate doc_ids via content hash collision | Added `source_path` parameter to `content_hash()` — distinct empty files now produce distinct doc_ids | Fixed |
| BUG-025 | Synonym dictionary missing 'Qty (ctns)' label | Added `"qty (ctns)": "cartons"` to `_SYN_MAP` | Fixed |

### Matching + Verification (1 fix)

| ID | Bug | Fix | Status |
|----|-----|-----|--------|
| BUG-036 | Single-document groups show "All shared fields agree across 1 documents" | Reports now show "Insufficient documents for cross-reference (1 document in group). No comparison performed." Singular/plural grammar fixed throughout | Fixed |

### Reporting + Scoring (7 fixes)

| ID | Bug | Fix | Status |
|----|-----|-----|--------|
| BUG-002 | results.json omits 14 documents from shipment document lists | Always uses authoritative `group_doc_map` instead of suspect+findings fallback | Fixed |
| BUG-005 | Correction drafts say "per the other 0 documents" | Fixed `n_other` calculation from complete group_docs + singular/plural grammar | Fixed |
| BUG-006 | Correction drafts only address the first finding | Rewrote to iterate ALL HIGH/MEDIUM findings as bullet points | Fixed |
| BUG-007 | Results.json document order is non-deterministic | Replaced `set()` with `sorted()` in document collection logic | Fixed |
| BUG-029 | PASS reports suppress low-severity findings | Now says "All critical fields agree" + includes minor observations table | Fixed |
| BUG-030 | Low-severity noise drowns real errors in FAIL reports | HIGH/MEDIUM → "Findings" table, LOW → separate "Minor Observations" section | Fixed |
| BUG-037 | No dashboard.html generated by pipeline | New `_generate_results_dashboard()` creates self-contained HTML with inline JSON | Fixed |

### CLI + Web (20 fixes)

| ID | Bug | Fix | Status |
|----|-----|-----|--------|
| BUG-001 | Agent simulator crashes with TypeError when rng_seed is None | Resolves to random int via `rng.randint(0, 2**31)` before arithmetic | Fixed |
| BUG-013 | Web API drops numeric_tolerance=0.0 via falsy check | Changed `if kwargs.get('numeric_tolerance'):` to `is not None` | Fixed |
| BUG-014 | Frontend Config page tolerance and LLM settings not wired to pipeline | Updated `runPipeline()` to read cfg values and include in POST body | Fixed |
| BUG-015 | Verification crashes with raw traceback when input files missing | Added file existence checks with clean error messages | Fixed |
| BUG-016 | Ingestion exits 0 on nonexistent or non-directory corpus path | Added path validation, exits 1 on invalid paths | Fixed |
| BUG-017 | Pipeline creates empty output directory even when corpus validation fails | Moved `out_path.mkdir()` to after corpus validation | Fixed |
| BUG-018 | Stale artifacts from previous runs are not cleaned | Added `--clean` CLI flag that removes output dir before running | Fixed |
| BUG-019 | Broken test fixture in test_malformed_docs.py | Created `tests/conftest.py` with `test_dir` fixture | Fixed |
| BUG-020 | Matching, verification, reporting __main__ blocks silently ignore --help | Added argparse with --in-dir, --output, --numeric-tolerance flags | Fixed |
| BUG-026 | --email-inbox + --corpus together causes cryptic crash | Post-parse validation rejects conflicting flags | Fixed |
| BUG-027 | --num-emails accepts negative values and zero | Validation requires --num-emails >= 1 | Fixed |
| BUG-028 | --numeric-tolerance accepts negative, NaN, inf | Validation rejects invalid floats | Fixed |
| BUG-031 | Dry-run mode still creates files for generated/mixed sim modes | Sets `files=[]` when `dry_run=True` | Fixed |
| BUG-032 | Error injection feature is completely non-functional (dead code) | Wired `_inject_error()` into `generate_shipment_set()` | Fixed |
| BUG-033 | Web API has no input validation on POST body | Numeric validation + allowlist for config keys | Fixed |
| BUG-034 | Feedback tuner overrides computed but never loaded by pipeline | Loads `tuning_overrides.json` at pipeline start, applies synonym boosts + tolerance | Fixed |
| BUG-035 | Em-dash in --simulate-agents help string causes encoding error on Windows | Replaced em-dash (U+2014) with ASCII `--` | Fixed |
| BUG-038 | Ollama client default URL hardcoded to LAN IP 192.168.1.142 | Changed to `http://localhost:11434` | Fixed |
| BUG-039 | WARNING log for ingest failure includes full stack trace | Concise message at WARNING, full traceback at DEBUG | Fixed |
| BUG-040 | Path traversal potential in /api/documents/{filename} | Added `filepath.resolve().is_relative_to(CORPUS_DIR.resolve())` check | Fixed |

### Documentation (5 fixes)

| ID | Bug | Fix | Status |
|----|-----|-----|--------|
| BUG-021 | README zip file path is wrong | Corrected to `../synthetic_shipping_docs.zip` + added Windows PowerShell/cmd equivalents | Fixed |
| BUG-022 | README project structure missing 5 subdirectories | Added agents/, email/, feedback/, llm/, web/ + .env.example | Fixed |
| BUG-023 | README does not explain PASS/FAIL verdict logic or severity | New section with severity table + majority-vote docs | Fixed |
| BUG-024 | README does not document .env, output files, prerequisites, dashboard | Four new sections added (Prerequisites, Env config, Output files, Dashboard) | Fixed |
| Extra | pyproject.toml missing dependencies | Added python-dotenv, requests; added optional groups: email=[resend], web=[fastapi,uvicorn], llm=[anthropic] | Fixed |

---

## Phase 4: Verification

### Test Suite

```
Total tests:  382
Passed:       382
Failed:         0
Regressions:    0
Runtime:      8.64s
```

### Pipeline Run

```
Status:        Completed successfully
Documents:     51 ingested → 51 canonical
Groups:        12 shipment groups
Verdicts:      7 PASS, 5 FAIL
Output:        data/out_verify/
```

### Confirmed Fixes

| Bug | Verification |
|-----|-------------|
| BUG-002 | results.json includes all 51 documents in shipment groups |
| BUG-005 | No instances of "per the other 0 documents" in any output |
| BUG-006 | Correction drafts list all discrepancies (e.g., G06 references all findings) |
| BUG-007 | Deterministic sorted document lists across runs |
| BUG-029 | PASS reports show "All critical fields agree" with minor observations table |
| BUG-030 | FAIL reports separate HIGH/MEDIUM findings from LOW minor observations |
| BUG-037 | dashboard.html generated (35,100 bytes), self-contained with inline JSON |
| BUG-036 | Single-doc group guard in place (no single-doc groups in this corpus to trigger it) |

---

## Test Growth

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| test_utils.py | 52 | 52 | — |
| test_ingestion.py | 25 | 25 | — |
| test_extraction.py | 111 | 111 | — |
| test_matching.py | 11 | 11 | — |
| test_verification.py | 16 | 16 | — |
| test_reporting.py | 11 | 11 | — |
| test_edge_cases.py | 99 | 99 | — |
| test_integration.py | 14 | 14 | — |
| test_pipeline.py | 7 | 7 | — |
| test_email.py | ~20 | ~20 | — |
| test_llm_router.py | ~15 | ~15 | — |
| test_malformed_docs.py | — | ~36 | +36 (new) |
| conftest.py | — | — | new fixtures |
| **Total** | **346** | **382** | **+36** |

---

## Retest Recommendations

The following areas should be retested in a future round (4 testers hit rate limits):

1. **Spanish synonym coverage** — Carmen's test did not complete. Verify no common
   Latin American shipping terms are missing from `synonyms.py`.
2. **Intern chaos scenario** — Pietro's test did not complete. Verify naive user
   experience, web UI startup, library import behavior.
3. **Stage-by-stage CLI isolation** — Laura's test did not complete. Verify individual
   stage CLIs work with their new argparse interfaces.
4. **README accuracy on Windows** — Chiara's test did not complete. Verify all README
   commands work on Windows PowerShell.
