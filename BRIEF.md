# BRIEF.md — docverify Project Dashboard

> **Last updated:** 2026-06-20 — Post Bug Hunt (40 bugs found & fixed)

---

## Status

**Phase 1 MVP: 100% implemented.** All five pipeline modules (Ingestion, Extraction,
Matching, Verification, Reporting) are built and tested. The scoring harness confirms
all four MVP targets are met. Three guardian reviews (Security, Simplicity, QA) are
complete. The engine is **GO for the Friday demo**.

**Bug Hunt (2026-06-20):** 20 simulated employee agents tested the MVP from every
angle (new users, Italian clerks, QA breakers, auditors, compliance officers, etc.).
Triage found **40 unique bugs**. 5 fixer agents patched all subsystems. **382/382 tests
pass, zero regressions.** See `BUG_HUNT_REPORT.md` for the full report.

---

## What It Does

docverify is a shipping document cross-reference verification engine. It takes a
folder of shipping documents (Bills of Lading, Packing Lists, Invoices, Pro Formas,
Confirmations) in .docx and .xlsx formats, figures out which documents belong to the
same shipment based on their content (order numbers, container numbers, etc.), and
flags every field that disagrees across the documents. It catches errors like wrong
order numbers, mismatched container IDs, or mismatched weights -- the kind of mistakes
that cause port delays, fines, and lost clients.

---

## Module Status

| Module | Status | Lines | Notes |
|---|---|---|---|
| Ingestion | Tested | 216 | docx + xlsx normalizer, content-hash doc_id |
| Extraction | Tested | 906 | Deterministic synonym dict (100+ labels, EN/IT/ES), Gemini LLM optional fallback |
| Matching | Tested | 267 | Content-based clustering, fuzzy identifier matching, majority-vote outlier |
| Verification | Tested | 505 | Cross-field comparison, severity levels, configurable numeric tolerance |
| Reporting | Tested | 341 | Per-shipment reports + results.json + correction email drafts |
| Pipeline + Scoring | Tested | 442 | CLI entrypoint, answer-key scorer, scorecard.json output |
| Schemas + Utils | Implemented | 270 | Pydantic v2 frozen models, parse_number, normalize_identifier, content_hash |

---

## Metrics vs Targets

| Metric | Target | Actual | Status |
|---|---|---|---|
| Discrepancy recall | 5/5 | 5/5 (100%) | PASS |
| False positives | 0 | 0 | PASS |
| Localization accuracy | >=4/5 | 5/5 (100%) | PASS |
| Grouping accuracy | 12/12 | 12/12 (100%) | PASS |
| F1 | -- | 1.0 | -- |
| Test suite | -- | 382/382 pass | All green (346 original + 36 bug hunt) |

Source: `data/out/scorecard.json`, `docverify/QA_REPORT.md`

---

## Key Decisions

- **Deterministic-first extraction.** A synonym dictionary handles all 60+ label
  variants (EN/IT/ES). LLM fallback (Gemini) exists but is off by default. Zero
  network calls in the core pipeline.
- **Content-based grouping.** Documents are clustered by order_no, bl_no, container_no,
  and reference -- filenames are treated as opaque. This matches the real-world scenario
  where files arrive via email with arbitrary names.
- **Majority-vote outlier.** When documents disagree, the engine identifies the
  minority-value document as the suspect. This requires at least 3 documents per
  shipment for reliable detection; 2-doc groups flag both as suspects.
- **Configurable numeric tolerance.** Default 0.0 (exact match). Exposed as a param
  for real-world float noise or currency rounding. Not stressed by current test corpus
  (all planted errors are identifier-level).
- **Privacy by design.** Pipeline runs fully offline. Only the optional Gemini fallback
  sends data (label strings + 500-char snippet, never whole documents). Gated behind
  `use_llm=True` + `GEMINI_API_KEY`.

---

## Guardian Summary

| Guardian | Verdict | Key Finding |
|---|---|---|
| Security (90) | PASS | No data leakage vectors. 2 Medium findings (file-size limits, unpinned deps) -- recommendations only, not blockers. |
| Simplicity (91) | PASS | ~30 lines of bloat removed (dead imports, redundant guards, global state). 1 latent bug fixed (`_KV_PATTERN` -> `_KV_FINDER`). |
| QA (92) | GO | 346/346 tests pass. 99 edge-case + 14 integration tests. No bugs found. |

Detailed reports: `SECURITY_AUDIT.md`, `SIMPLICITY_REVIEW.md`, `docverify/QA_REPORT.md`

---

## Known Issues / Risks

1. **xlsx doc_type classification** -- xlsx invoices without explicit "Commercial Invoice"
   text may classify as `unknown`. Does not affect verification accuracy (matching uses
   identifiers, not doc_type), but metadata is less precise. (QA observation #1)
2. **~~LOW-severity line-item noise~~** — **FIXED (BUG-030).** FAIL reports now separate
   HIGH/MEDIUM findings from LOW-severity noise. LOW findings go to a "Minor Observations"
   section. PASS reports say "All critical fields agree" when only LOW findings exist.
3. **Synthetic corpus limitations** -- all planted errors are identifier-level. Numeric
   mismatch path (the real-world failure mode Massimo described: 6,402 vs 6,302 kg) is
   implemented and unit-tested but not stressed end-to-end by this fixture set.
4. **Dependency pinning** -- `requirements.txt` uses unpinned versions. Security audit
   recommends pinning to exact versions. (pyproject.toml deps now match requirements.txt
   after BUG-024 fix.)
5. **File-size limits** -- no ingestion guard against maliciously large files. Security
   audit recommends a 50MB cap.
6. **~~Path traversal in web API~~** — **FIXED (BUG-040).** `/api/documents/{filename}`
   now validates the resolved path is inside the corpus directory.
7. **Rate limits on parallel agent testing** — 4 of 20 tester agents hit 429 rate limits
   during the bug hunt. Spanish synonym coverage and intern chaos scenarios should be
   retested in a future round.

---

## Open Questions for Friday's Call with Nasim

1. **Document types:** Synthetic corpus has 5 types (B/L, packing list, commercial
   invoice, proforma invoice, confirmation). Does the real workflow include others?
   (Certificate of Origin, insurance cert, weight cert?)
2. **File formats:** Always PDF? Scanned images requiring OCR? Native Excel? The
   current engine handles .docx and .xlsx only.
3. **Container numbers:** B/L docs embed container type/size after the number
   (e.g., `WSHZ2980815  40'HC`). Is this consistent in real docs?
4. **Party names:** Addresses sometimes embedded in shipper/consignee field, sometimes
   not. How consistent are real documents?
5. **Numeric tolerance:** Should any field ever be allowed to differ slightly? What is
   the policy for currency rounding vs weight precision?
6. **Volume:** Shipments per month? Determines infrastructure sizing.
7. **Who reviews flags:** When the engine flags a discrepancy, who reviews it? What is
   the correction workflow?
8. **ERP/WMS integration:** Do documents come from an existing system with structured
   data we can tap directly?
9. **Authorization:** When can we receive real (redacted) sample documents to test
   against?
10. **Extra doc types not in our scope yet:** Are there documents we haven't seen that
    need cross-referencing?

---

## Changelog

- (2026-06-20) — **Bug Hunt completed.** 20 simulated employee tester agents + 5 fixer
  agents. 40 bugs found and fixed across all subsystems. Test suite: 346 → 382 (36 new
  tests). Zero regressions. Key fixes: XLSX extraction (line items, totals, watermarks),
  legacy DOCX totals, confirmation vessel parsing, deterministic output, correction drafts
  now list all findings, dashboard.html auto-generated, CLI validation hardened, web API
  security (path traversal), feedback tuner wired up, `--clean` flag added.
- `7a7b729` (2026-06-17) -- Initial BRIEF.md created. All modules implemented and
  tested. Security, Simplicity, QA reviews complete. All MVP targets met. GO for
  Friday demo.
