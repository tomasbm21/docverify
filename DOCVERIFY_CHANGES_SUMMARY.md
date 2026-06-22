# DocVerify — Changes Summary

> All changes from the 27-agent bug hunt (2026-06-20) that need to be reflected in the
> web UI and user-facing surfaces.

---

## What Changed in the Backend (already deployed)

### Pipeline (`pipeline.py`)
- **`--clean` flag** — wipes output directory before running (BUG-018)
- **Feedback tuner integration** — loads `tuning_overrides.json` at startup, applies synonym
  boosts and tolerance adjustments (BUG-034)
- **Input validation** — rejects NaN/inf/negative tolerance, negative num-emails,
  conflicting flags (BUG-026, 027, 028)
- **Groups passed to report** — `report()` now receives groups for authoritative doc lists (BUG-002)
- **Em-dash fix** — help string uses ASCII `--` for Windows compatibility (BUG-035)

### Reporting (`report.py`)
- **All 51 documents in results.json** — PASS verdicts no longer omit documents (BUG-002)
- **Correction drafts list ALL findings** — every HIGH/MEDIUM finding as a bullet point,
  not just the first one (BUG-006)
- **Deterministic output** — `sorted()` instead of `set()` for byte-identical results (BUG-007)
- **PASS reports: "All critical fields agree"** — with minor observations table for LOW
  findings (BUG-029)
- **FAIL reports: severity separation** — HIGH/MEDIUM in "Findings" table, LOW in "Minor
  Observations" section (BUG-030)
- **Single-doc group guard** — "Insufficient documents for cross-reference" message (BUG-036)
- **Dashboard.html auto-generated** — self-contained HTML with inline JSON, filterable
  table, click-to-expand details (BUG-037)

### Extraction (`extract.py`)
- **XLSX line items fixed** — header row scoring rewrite, amount fallback computation,
  watermark/specimen skip (BUG-003, 004, 008)
- **Legacy DOCX totals** — new `_parse_legacy_totals()` fallback (BUG-009)
- **Unit suffix stripping** — "1119 CTNS" → 1119 (BUG-010)
- **Vessel/voyage split** — "JOHNSON STAR voyage 875E" → "JOHNSON STAR 875E" (BUG-011)
- **Missing synonym** — "qty (ctns)" → cartons (BUG-025)

### Web API (`api.py`)
- **Path traversal guard** — `is_relative_to()` check on document endpoint (BUG-040)
- **Config allowlist** — rejects unknown config keys (BUG-033)
- **Input validation** — numeric_tolerance and num_emails validated (BUG-033)
- **`is not None` check** — numeric_tolerance=0.0 no longer dropped (BUG-013)

### Other
- **Ollama default URL** — changed from `192.168.1.142` to `localhost` (BUG-038)
- **Ingest log** — concise WARNING, full traceback at DEBUG (BUG-039)
- **Agent simulator** — rng_seed fix, dry-run guard, error injection wired (BUG-001, 031, 032)

---

## What the UI Needs to Reflect

### 1. Dashboard Page
- [ ] Show bug hunt status: "40 bugs found & fixed · 382 tests · 0 regressions"
- [ ] Add `--clean` toggle to Quick Actions ("Clean output before run")
- [ ] Show feedback tuner status: "Tuner active" or "No overrides loaded"
- [ ] Update test count references from 346 to 382

### 2. Results Page
- [ ] Separate findings by severity in detail view:
  - HIGH/MEDIUM → "Findings" section (actionable)
  - LOW → "Minor Observations" section (informational)
- [ ] Show all documents in group detail (BUG-002 fix — no more missing docs)
- [ ] Show correction draft preview with ALL findings as bullet points
- [ ] Add link/button to open auto-generated dashboard.html
- [ ] For PASS verdicts with LOW findings: show "All critical fields agree" + minor table
- [ ] For single-doc groups: show "Insufficient documents for cross-reference"

### 3. Config Page
- [ ] Update Ollama URL placeholder from `192.168.1.142` to `localhost`
- [ ] Add `--clean` flag toggle in Pipeline Settings
- [ ] Show validation errors inline (NaN, negative, etc.)
- [ ] Add feedback tuner status display
- [ ] Show allowed config keys (reject unknown keys with clear error)

### 4. Documents Page
- [ ] Path traversal protection already in backend — show "Access denied" error gracefully

### 5. General
- [ ] Update any hardcoded "346 tests" to "382 tests"
- [ ] Add "Bug Hunt Report" link/tab or info card
- [ ] Version bump indicator (0.2.0 → 0.3.0)

---

## Files That Changed

| File | Lines Changed | Impact |
|------|--------------|--------|
| `pipeline.py` | ~60 | --clean flag, validation, feedback tuner, groups→report |
| `reporting/report.py` | ~120 | Severity separation, dashboard gen, correction drafts, deterministic output |
| `extraction/extract.py` | ~80 | XLSX fixes, legacy totals, vessel parsing |
| `extraction/synonyms.py` | 1 | New synonym |
| `utils.py` | 10 | content_hash source_path, parse_number suffix strip |
| `ingestion/ingest.py` | 15 | Path validation, log improvement |
| `verification/verify.py` | 10 | File existence checks |
| `web/api.py` | 25 | Path traversal, config allowlist, validation |
| `web/static/app.js` | 10 | Config values wired to pipeline |
| `agents/simulator.py` | 15 | rng_seed, dry-run, error injection |
| `agents/generator.py` | 10 | Error injection wiring |
| `llm/ollama_client.py` | 1 | Default URL |
| `feedback/tuner.py` | 20 | load_overrides, apply_overrides_to_synonyms |
| `pyproject.toml` | 15 | Dependencies |
| `README.md` | ~100 | Major rewrite |
| `BRIEF.md` | ~20 | Status, test count, known issues |
| `FINDINGS.md` | ~40 | Bug hunt section |
| `QA_REPORT.md` | ~80 | Bug hunt section |
| `TECHNICAL_DOC.md` | ~15 | Test count, dashboard status |
| `tests/conftest.py` | NEW | Shared fixtures |
| `tests/test_malformed_docs.py` | NEW | 36 new tests |
| `BUG_HUNT_REPORT.md` | NEW | Full report |
| `BUG_HUNT_CHANGELOG.md` | NEW | Full changelog |
