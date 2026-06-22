# SIMPLICITY_REVIEW.md — Anti-Bloat / Simplicity Review

> **Agent 91** | Reviewed 2026-06-17
> All findings verified against a green test baseline (233/233 passed).

---

## Findings Table

| # | File:Line | Category | Severity | Finding | Action |
|---|-----------|----------|----------|---------|--------|
| 1 | `extraction/extract.py:11` | Dead import | Bloat-Low | `from typing import Optional` imported but never used | **Applied** — removed |
| 2 | `matching/match.py:23` | Dead import | Bloat-Low | `from typing import Optional` imported but never used | **Applied** — removed |
| 3 | `matching/match.py:250` | Dead import | Bloat-Low | `CanonicalDoc` re-imported in `__main__` block but already imported at module level | **Applied** — removed |
| 4 | `extraction/extract.py:285` | Duplication | Bloat-Low | `"total"` appears twice in tuple `("total", "totale", "total", "")` | **Applied** — removed duplicate |
| 5 | `reporting/report.py:113-136` | Dead code | Bloat-Med | `_doc_ids_for_group()` defined but never called anywhere in the codebase | **Applied** — removed |
| 6 | `reporting/report.py:33` | Redundant guard | Bloat-Low | `hasattr(f.severity, "value")` — `Severity` is `str, Enum`, always has `.value` | **Applied** — simplified to `.value` |
| 7 | `reporting/report.py:42` | Redundant guard | Bloat-Low | `hasattr(doc.doc_type, "value")` — same as above for `DocType` | **Applied** — simplified to `.value` |
| 8 | `reporting/report.py:160` | Redundant guard | Bloat-Low | `hasattr(f.severity, 'value')` in markdown table row | **Applied** — simplified to `.value` |
| 9 | `reporting/report.py:224-225,243` | Over-abstraction | Bloat-Med | Module-level mutable global `doc_index` mutated via `global` statement; passed implicitly to helpers | **Applied** — made local to `report()`, passed as parameter to `_write_markdown_report` |
| 10 | `extraction/extract.py:809` | Latent bug | Bloat-High | `_KV_PATTERN.match(line)` references undefined name; actual regex is `_KV_FINDER` (line 81). Would crash at runtime if `use_llm=True` with unresolved labels. | **Applied** — fixed to `_KV_FINDER.match(line)` |
| 11 | `extraction/extract.py:45-73` | Function size | Bloat-Low | `extract_one()` is ~200 lines. Internally well-structured with clear numbered sections, but long for a single function. | **Recommendation** — split sections 6-7 (line-item + totals parsing) into `_extract_items_and_totals()` if the function grows further |
| 12 | `extraction/extract.py:456-468,535-548` | Duplication | Bloat-Low | Header-line search logic in `_parse_legacy_packing_list` and `_parse_legacy_totals` is copy-pasted (same keyword list, same regex guard). | **Recommendation** — extract `_find_legacy_header(lines) -> int` helper |
| 13 | `ingestion/ingest.py:10`, `matching/match.py:20` | Consistency | Bloat-Low | `from __future__ import annotations` used in 2 of 7 modules. Unnecessary on Python 3.11+ (the project target). Other modules omit it. | **Recommendation** — either add to all modules or remove from these two for consistency |
| 14 | `schemas/models.py:7` | Consistency | Bloat-Low | Uses `from typing import Optional` while all other modules use native `str \| None` syntax. | **Recommendation** — modernize to `str \| None` (touches frozen schema, so defer to Architect) |
| 15 | `reporting/report.py:57-62,79-87` | Over-abstraction | Bloat-Low | `_consensus_identifiers` and `_totals_from_docs` each define a local `majority()` function with `from collections import Counter` inside it. The import is repeated and the pattern is duplicated. | **Recommendation** — extract shared `_majority_value(vals) -> str \| None` helper, import `Counter` at module top |
| 16 | `verification/verify.py:165-240` | Duplication | Bloat-Low | `_compare_li_values()` duplicates the majority-vote + finding-creation logic from `_compare_section()`. Different only in that it iterates over `_LI_NUMERIC_FIELDS + _LI_COUNT_FIELDS` and uses a different tolerance check. | **Recommendation** — consider unifying with `_compare_section` via a `section_obj_getter` callback |
| 17 | `verification/verify.py:54-58` | Dead code | Bloat-Low | `_to_str()` is a trivial wrapper (`str(val) if val is not None else None`). Used ~12 times. Marginal — the wrapper adds a function call for what inline `str(v) if v is not None else None` does. | **Recommendation** — acceptable as-is; keep for readability if desired |

---

## Summary of Applied Changes

| Metric | Count |
|--------|-------|
| Unused imports removed | 3 |
| Dead functions removed | 1 (`_doc_ids_for_group`) |
| Redundant guards simplified | 3 (`hasattr` -> direct `.value`) |
| Duplicate string literals fixed | 1 |
| Latent bugs fixed | 1 (`_KV_PATTERN` -> `_KV_FINDER`) |
| Global mutable state eliminated | 1 (`doc_index`) |
| **Total lines removed** | **~30** |
| **Deps trimmed** | **0** (all `requirements.txt` entries are used) |
| **Test regressions** | **0** (233/233 green before and after) |

---

## Complexity Hotspots

These areas are proportional now but risk growing disproportionately:

1. **`extraction/extract.py` — `extract_one()`** (~200 lines, 10 numbered sections). If the extraction logic needs to handle more document formats or edge cases, this function should be decomposed. The legacy fixed-width parser (`_parse_legacy_packing_list`) is already ~80 lines on its own.

2. **`extraction/synonyms.py` — `_SYN_MAP` dict** (210+ entries). This is the right pattern (data-driven, not code-driven) but will need maintenance as new label variants appear. Consider loading from a YAML/JSON file if it exceeds ~500 entries.

3. **`verification/verify.py` — `_compare_section()` + `_compare_li_values()`**. Two comparison functions with overlapping logic. If a third comparison type is added, refactor into a single generic comparator.

4. **`reporting/report.py` — doc-id reconstruction**. The `report()` function reconstructs group membership from findings+suspects because the `ShipmentVerdict` model doesn't carry `doc_ids`. The `groups` parameter was added as a workaround. If the verdict model ever gains `doc_ids`, the reconstruction logic can be removed entirely.

5. **`scoring/score.py` — `_map_groups_to_shipments()`**. Relies on filename prefix matching (`S{nn}`) which is correct for the scorer but fragile. If the ground-truth format changes, this function needs updating.

---

## Dependencies Audit

All entries in `requirements.txt` are used:

| Package | Used by | Verdict |
|---------|---------|---------|
| `pydantic>=2` | `schemas/models.py` (all models) | Keep |
| `python-docx` | `ingestion/ingest.py` (`_read_docx`) | Keep |
| `openpyxl` | `ingestion/ingest.py` (`_read_xlsx`) | Keep |
| `rapidfuzz` | `matching/match.py` (fuzzy fallback) | Keep |
| `pytest` | All test files | Keep |
| `google-generativeai` | `extraction/llm_fallback.py` (optional) | Keep |

No unused or redundant dependencies.
