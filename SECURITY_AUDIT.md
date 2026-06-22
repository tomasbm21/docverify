# SECURITY_AUDIT.md — docverify Engine

> **Auditor:** Agent 90 (Security & Data-Privacy Guardian)
> **Date:** 2026-06-17
> **Scope:** Full source tree audit against CONTRACTS.md section 6, MVP_BUILD_PROMPT.md section 0,
> and INTEGRATION.md data-privacy contract.
> **Status:** PASS with findings (no Critical issues; safe fixes applied where possible).

---

## Findings Table

| # | Severity | Location | Issue | Fix / Recommendation |
|---|----------|----------|-------|---------------------|
| 1 | **Medium** | `ingestion/ingest.py:92-137` | No file size limit on `.docx`/`.xlsx` ingestion. A maliciously large or zip-bomb-style file could exhaust memory. `openpyxl` and `python-docx` both decompress zip archives internally without size bounds. | **Recommendation:** Add a `MAX_FILE_SIZE` constant (e.g. 50 MB) and check `fpath.stat().st_size` before calling `ingest_file()`. Log and skip oversized files. |
| 2 | **Medium** | `requirements.txt:1-6` | Dependencies are not pinned to specific versions (`pydantic>=2`, etc.). A supply-chain attack via a compromised PyPI release could inject malicious code. Also, `pytest` and `google-generativeai` are in the main requirements file rather than separated as dev/optional. | **Recommendation:** Pin all deps to exact versions (e.g. `pydantic==2.11.3`). Move `pytest` to a `[dev]` extra and `google-generativeai` to an `[llm]` extra in `pyproject.toml` (already done there; align `requirements.txt`). Consider running `pip-audit` periodically. |
| 3 | **Low** | `extraction/llm_fallback.py:120` | `logger.warning("Gemini API call failed", exc_info=True)` logs a full traceback. If the Gemini SDK embeds request/response content in the exception, document snippets could leak to logs. At WARNING level this is visible in production. | **Recommendation:** Change to `logger.warning("Gemini API call failed — ignoring LLM fallback")` without `exc_info=True`, or log only `type(e).__name__` + `str(e)` separately. |
| 4 | **Low** | `pipeline.py:142` | `logger.error("Pipeline failed: %s", e)` — if the exception message includes file paths or partial content, it could leak into logs. | **Note:** Low risk since the pipeline orchestrator only receives high-level exceptions (FileNotFoundError, etc.), not document content. No change required, but be aware if exception types change. |
| 5 | **Info** | `.env.example:1-3` | The no-train note is present but could be stronger. Suggest adding explicit warning about free-tier keys. | **Applied:** See `.env.example` update below. |
| 6 | **Info** | `requirements.txt:6` | `google-generativeai` is a top-level dependency. For deployments that never use LLM, this widens the attack surface unnecessarily. | **Note:** `pyproject.toml` correctly separates it under `[project.optional-dependencies] llm`. `requirements.txt` should match. |

---

## Checklist Results

### 1. No raw-document leakage to external services

**PASS.** The only permitted outbound call is the Gemini fallback in `extraction/llm_fallback.py`.

- `import requests`, `urllib`, `httpx`, `smtplib`, `socket`, `urlopen` — **none found** anywhere in the source tree.
- The Gemini fallback is gated behind `use_llm=True` AND a present `GEMINI_API_KEY` (`llm_fallback.py:47-49`).
- The fallback sends only unresolved label strings + a 500-char document snippet (`extract.py:804`), not whole documents.
- The docstring explicitly states the zero-retention requirement (`llm_fallback.py:5-9`).
- `use_llm=False` is the default throughout: `pipeline.py:124`, `extract.py:639`, `extract.py:847`.

### 2. Secret handling

**PASS.**

- `GEMINI_API_KEY` read only from `os.environ.get()` (`llm_fallback.py:47`).
- Never hardcoded, never printed, never written to any output/log/JSON.
- The warning message says "GEMINI_API_KEY not set" without echoing the value (`llm_fallback.py:49`).
- `.env` is gitignored (`.gitignore:2`). `.env.example` has an empty key with a no-train note.
- `git ls-files` confirms no `.env` is tracked.
- Grep for key-like strings (`API_KEY`, `SECRET`, `TOKEN`, `PASSWORD`) found only references to the env var name, not actual values.

### 3. No sensitive data in logs

**PASS.**

- `get_logger()` returns a WARNING-level logger (`utils.py:135-148`).
- The Gemini prompt payload is logged at DEBUG level only (`llm_fallback.py:79`), which is below WARNING and never emitted by default.
- `ingest.py:188` logs filename on failure (`exc_info=True`), not document content.
- `pipeline.py:142` logs exception type/message only.

### 4. No sensitive data committed

**PASS.**

- `data/` (corpus + outputs) is gitignored (`.gitignore:1`).
- `git ls-files` shows no documents, `results.json`, reports, `.env`, or `answer_key.json` in the tracked tree.
- `answer_key.json` is not copied into the engine package — it's referenced by path in `scoring/score.py:251`.
- Test fixtures (`tests/fixtures/`) contain synthetic sample documents, which is expected and safe.

### 5. Determinism / no exfiltration side-channels

**PASS.**

- With `use_llm=False`, the core pipeline makes zero network calls. All imports of `google.generativeai` are lazy and only triggered inside `llm_fallback.py` when explicitly called (`llm_fallback.py:53`).
- `test_extraction.py:TestOfflineOperation.test_use_llm_false_no_import` explicitly verifies that `google-generativeai` is never imported when `use_llm=False`.
- The pipeline is fully reproducible: same inputs produce same `doc_id` (SHA-256 of normalized text), same extractions, same groupings, same verdicts.

### 6. Dependency hygiene

**PASS with notes (Finding #2, #6).**

- `requirements.txt` contains 6 packages. All are well-known, widely used, from trusted sources (PyPI).
- `pydantic`, `python-docx`, `openpyxl`, `rapidfuzz` — all standard Python libraries for their respective tasks.
- `pytest` — test-only, but present in main requirements.txt (should be dev-only).
- `google-generativeai` — optional, but present in main requirements.txt (should be llm-only).
- No unexpected or suspicious packages.
- No known advisories detected by manual review (recommend `pip-audit` for automated checking).

### 7. Input safety

**PASS with notes (Finding #1).**

- `openpyxl.load_workbook(path, data_only=True)` — `data_only=True` returns cached formula values, does NOT execute macros. No `keep_vba` parameter used.
- `python-docx` reads XML from the zip archive; does not execute embedded content.
- No external link following or macro execution anywhere in the codebase.
- **Path handling:** All filenames come from `corpus_path.iterdir()` (controlled directory), not from user-supplied strings. Output paths use `os.path.join(out_dir, ...)` with fixed subdirectory names (`reports/`, `corrections/`). No path traversal vector identified.
- **Size limits:** No file size check before ingestion (Finding #1). A multi-GB zip-bomb `.docx` could cause memory exhaustion.

### 8. Production-readiness notes (for Phase 2-3)

**Not yet applicable** — current system runs on synthetic data only. Before real client documents flow through:

1. **Enforce zero-retention endpoints:** The Gemini fallback docstring states the requirement, but there is no runtime check that the API key is associated with a paid/no-train account. Add a configuration flag or documentation requirement.
2. **Encryption at rest:** The `data/` directory (corpus + outputs) is stored in plaintext. Real shipments should be encrypted at rest (disk encryption or application-level).
3. **Access control:** No authentication or authorization on the pipeline. The CLI is open. For production, add RBAC around who can run the pipeline and access outputs.
4. **Audit logging:** No audit trail of who ran the pipeline, when, and on what documents. Add structured audit logs for compliance.
5. **Network isolation:** For production, consider running the pipeline in an environment with no outbound network access (except the specific Gemini endpoint if LLM is used). Use egress firewall rules.
6. **Data retention policy:** Define how long `data/out/` artifacts are retained and implement automatic purging.

---

## Safe Fixes Applied

### `.env.example` — strengthened no-train note

Added explicit warning about free-tier keys.

---

## Commit

```
chore(security): privacy + secrets audit, SECURITY_AUDIT.md
```
