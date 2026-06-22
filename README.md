# docverify — Shipping Document Cross-Reference Verification Engine

Phase 1 MVP of a document verification system for a pasta import/export logistics
operation (Italy -> Lebanon/UAE/HK). Ingests .docx/.xlsx shipping documents, groups
them by shipment from content alone, and flags every field that disagrees across
documents in a shipment.

## Prerequisites

- **Python 3.11+** (uses `match` statements, `str | None` union syntax, Pydantic v2)

## Setup

```bash
cd "PASTA PROJ/docverify"

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

## Unzip the test corpus

The zip file lives one level up from the `docverify/` directory:

```bash
# Linux/macOS:
unzip ../synthetic_shipping_docs.zip -d data/corpus/

# Windows (PowerShell):
Expand-Archive -Path ..\synthetic_shipping_docs.zip -DestinationPath data\corpus

# Windows (cmd):
tar -xf ..\synthetic_shipping_docs.zip -C data\corpus
```

This extracts 51 documents (41 .docx, 10 .xlsx) into `data/corpus/`.

## Environment configuration (optional)

Copy `.env.example` to `.env` to enable optional features:

```bash
# Linux/macOS:
cp .env.example .env

# Windows (PowerShell):
Copy-Item .env.example .env
```

The `.env` file controls:

| Variable | Purpose | Required? |
|---|---|---|
| `LLM_PROVIDER` | LLM backend for extraction fallback (`ollama`, `anthropic`, `gemini`) | No (default: `ollama`) |
| `GEMINI_API_KEY` | Google Gemini API key (paid/no-train key only) | Only if `--use-llm` with Gemini |
| `ANTHROPIC_API_KEY` | Anthropic API key | Only if using Anthropic provider |
| `OLLAMA_BASE_URL` | Ollama server URL for local LLM | Only if using Ollama |
| `RESEND_API_KEY` | Resend API key for sending correction emails | No (drafts generated without it) |
| `EMAIL_*` | IMAP config for inbox polling (Phase 3) | No |

**The pipeline runs fully offline by default.** No API keys are needed for the core workflow.

## Run the pipeline

```bash
python -m docverify.pipeline --corpus data/corpus --out data/out
```

Add `--use-llm` to enable the LLM fallback for extraction (requires API key in `.env`).
Add `--numeric-tolerance 0.01` to allow small float differences.

## Verdict logic: PASS / FAIL

Each shipment group receives a **PASS** or **FAIL** verdict based on the severity of its findings:

| Severity | Assigned to | Effect on verdict |
|---|---|---|
| **HIGH** | Identifier mismatches (order no, B/L no, container no, etc.), numeric total mismatches (weight, value, cartons), currency mismatches, line-item value mismatches | Triggers **FAIL** |
| **MEDIUM** | Party name mismatches (shipper, consignee) after normalization | Triggers **FAIL** |
| **LOW** | Logistics field differences (vessel, voyage, port, date), line items present in only one document | Reported but does **NOT** trigger FAIL |

**Rule:** A shipment FAILs if any finding has severity HIGH or MEDIUM. LOW-severity findings are informational only.

When documents disagree, the engine uses **majority vote** to identify the outlier document (the "suspect"). In a 2-document group with a disagreement, both documents are flagged as suspects since the outlier cannot be determined.

## Output files

After a successful run, `data/out/` contains:

| File | Description |
|---|---|
| `raw_docs.json` | Stage A output — ingested document text, tables, and content hashes |
| `canonical_docs.json` | Stage B output — extracted typed fields per document |
| `groups.json` | Stage C output — shipment groupings with match certainty |
| `verdicts.json` | Stage D output — per-shipment PASS/FAIL verdicts with findings |
| `results.json` | Stage E output — combined results (dashboard feed) |
| `scorecard.json` | Scoring output — recall, precision, F1 vs answer key |
| `reports/*.md` | Per-shipment human-readable markdown reports |
| `corrections/*.txt` | Draft correction-request emails |

## Dashboard

An interactive HTML dashboard is available at `data/out/dashboard.html`. To view it:

```bash
cd data/out
python -m http.server 8080
# Open http://localhost:8080/dashboard.html in your browser
```

The dashboard reads `results.json` and provides a visual overview of all shipment verdicts, findings, and suspect documents.

## Run tests

```bash
pytest tests/ -q
```

## Key references

- [CONTRACTS.md](../agent_prompts/CONTRACTS.md) — frozen schema and file contracts
- [MVP_BUILD_PROMPT.md](../MVP_BUILD_PROMPT.md) — authoritative product spec
- [INTEGRATION.md](../INTEGRATION.md) — cross-agent interface map and data flow
- [TECHNICAL_DOC.md](./TECHNICAL_DOC.md) — full technical documentation

## Project structure

```
docverify/
├── docverify/
│   ├── schemas/
│   │   └── models.py          # Canonical Pydantic models (FROZEN)
│   ├── utils.py               # Shared helpers (hash, parse, normalize)
│   ├── pipeline.py            # End-to-end orchestrator CLI
│   ├── ingestion/             # Agent 01 — file readers (.docx + .xlsx)
│   ├── extraction/            # Agent 02 — field extraction + synonym mapping
│   ├── matching/              # Agent 03 — shipment clustering (union-find)
│   ├── verification/          # Agent 04 — cross-doc comparison + verdicts
│   ├── reporting/             # Agent 05 — reports + correction drafts
│   ├── scoring/               # Agent 06 — answer key scoring harness
│   ├── agents/                # Test data generators + personas for simulation
│   ├── email/                 # Email inbox polling + correction sender
│   ├── feedback/              # Dashboard, retraining, tuning, tracking tools
│   ├── llm/                   # LLM client abstraction (Ollama, Anthropic, Gemini)
│   └── web/                   # Web UI for reviewing flagged shipments
├── data/                      # gitignored: corpus + outputs
│   ├── corpus/                # 51 unzipped test documents
│   └── out/                   # Pipeline output files (see "Output files" above)
├── tests/                     # pytest suite (382 tests)
├── BUG_HUNT_REPORT.md         # Full bug hunt report (40 bugs found & fixed)
├── .env.example               # Environment variable template
├── requirements.txt
├── pyproject.toml
└── README.md
```
