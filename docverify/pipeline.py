"""Pipeline orchestrator / CLI entrypoint.

OWNER: Agent 06 — Integration + Scoring.
Wires the five modules (Ingestion -> Extraction -> Matching -> Verification -> Reporting)
into one end-to-end pipeline. Persists each stage's JSON to --out for debuggability.

Phase 2: Supports three ingestion modes:
  1. --corpus (default): Read from local directory (Phase 1 behavior)
  2. --email-inbox: Poll IMAP inbox for unread emails with attachments
  3. --simulate-agents: Agent simulation sends emails, then pipeline processes them
"""

import argparse
import json
import sys
from pathlib import Path

from docverify.utils import get_logger

logger = get_logger(__name__)


def _persist_json(data: list, path: Path) -> None:
    """Write a list of pydantic models (or dicts) to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_pipeline(corpus_dir: str, out_dir: str, use_llm: bool, numeric_tolerance: float, clean: bool = False) -> dict:
    """Execute the full pipeline: Ingest -> Extract -> Match -> Verify -> Report.

    Persists each stage's JSON to out_dir. Returns the results dict from reporting.
    Never crashes on a single bad document; surfaces non-zero exit only on real
    failures (e.g. corpus dir missing).
    """
    import shutil

    from docverify.ingestion.ingest import ingest_dir
    from docverify.extraction.extract import extract
    from docverify.matching.match import match
    from docverify.verification.verify import verify
    from docverify.reporting.report import report

    corpus_path = Path(corpus_dir)
    if not corpus_path.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    out_path = Path(out_dir)

    # BUG-018: clean stale artifacts if requested
    if clean and out_path.exists():
        shutil.rmtree(out_path)

    # BUG-017: mkdir after corpus validation
    out_path.mkdir(parents=True, exist_ok=True)

    # BUG-034: Load feedback overrides if available
    try:
        from docverify.feedback.tuner import FeedbackTuner
        tuner = FeedbackTuner()
        overrides = tuner.load_overrides()
        if overrides.feedback_count > 0:
            logger.info("Loaded feedback overrides (%d records)", overrides.feedback_count)
            # Apply synonym boosts from feedback
            from docverify.feedback.tuner import apply_overrides_to_synonyms
            apply_overrides_to_synonyms(overrides)
            # Use feedback-adjusted tolerance if the user didn't explicitly set one
            if numeric_tolerance == 0.0 and overrides.numeric_tolerances:
                numeric_tolerance = max(overrides.numeric_tolerances.values())
                logger.info("Adjusted numeric_tolerance to %.4f from feedback", numeric_tolerance)
    except Exception:
        logger.debug("No feedback overrides available", exc_info=True)

    # Stage A: Ingestion
    print(f"[A] Ingesting from {corpus_dir} ...")
    raw_docs = ingest_dir(corpus_dir)
    _persist_json(
        [d.model_dump(mode="json") for d in raw_docs],
        out_path / "raw_docs.json",
    )
    print(f"    -> {len(raw_docs)} documents ingested")

    # Stage B: Extraction
    print(f"[B] Extracting fields (use_llm={use_llm}) ...")
    canonical_docs = extract(raw_docs, use_llm=use_llm)
    _persist_json(
        [d.model_dump(mode="json") for d in canonical_docs],
        out_path / "canonical_docs.json",
    )
    print(f"    -> {len(canonical_docs)} canonical records")

    # Stage C: Matching
    print("[C] Matching into shipment groups ...")
    groups = match(canonical_docs)
    _persist_json(
        [g.model_dump(mode="json") for g in groups],
        out_path / "groups.json",
    )
    print(f"    -> {len(groups)} shipment groups")

    # Stage D: Verification
    print(f"[D] Verifying (tolerance={numeric_tolerance}) ...")
    verdicts = verify(groups, canonical_docs, numeric_tolerance=numeric_tolerance)
    _persist_json(
        [v.model_dump(mode="json") for v in verdicts],
        out_path / "verdicts.json",
    )
    passed = sum(1 for v in verdicts if v.verdict == "PASS")
    failed = sum(1 for v in verdicts if v.verdict == "FAIL")
    print(f"    -> {passed} PASS, {failed} FAIL")

    # Stage E: Reporting
    print("[E] Generating reports ...")
    results = report(verdicts, canonical_docs, str(out_path), groups=groups)
    print(f"    -> results.json + {len(verdicts)} reports written")

    # Summary
    print()
    print("=" * 50)
    print("PIPELINE SUMMARY")
    print("=" * 50)
    print(f"  Documents ingested : {len(raw_docs)}")
    print(f"  Canonical records  : {len(canonical_docs)}")
    print(f"  Shipment groups    : {len(groups)}")
    print(f"  Verdicts PASS      : {passed}")
    print(f"  Verdicts FAIL      : {failed}")
    print(f"  Output directory   : {out_path.resolve()}")
    print("=" * 50)

    return results


def run_email_pipeline(out_dir: str, use_llm: bool, numeric_tolerance: float) -> dict:
    """Pipeline variant that ingests documents from email inbox.

    Polls IMAP for unread emails with .docx/.xlsx attachments,
    then runs the standard extraction -> matching -> verification -> reporting pipeline.
    """
    from docverify.email.inbox import fetch_unread_docs
    from docverify.extraction.extract import extract
    from docverify.matching.match import match
    from docverify.verification.verify import verify
    from docverify.reporting.report import report

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Stage A: Email Ingestion
    print("[A] Polling email inbox for documents ...")
    raw_docs = fetch_unread_docs()
    if not raw_docs:
        print("    -> No documents found in inbox")
        return {"shipments": [], "total_docs": 0}

    _persist_json(
        [d.model_dump(mode="json") for d in raw_docs],
        out_path / "raw_docs.json",
    )
    print(f"    -> {len(raw_docs)} documents from email")

    # Stages B-E: Standard pipeline
    print(f"[B] Extracting fields (use_llm={use_llm}) ...")
    canonical_docs = extract(raw_docs, use_llm=use_llm)
    _persist_json(
        [d.model_dump(mode="json") for d in canonical_docs],
        out_path / "canonical_docs.json",
    )
    print(f"    -> {len(canonical_docs)} canonical records")

    print("[C] Matching into shipment groups ...")
    groups = match(canonical_docs)
    _persist_json(
        [g.model_dump(mode="json") for g in groups],
        out_path / "groups.json",
    )
    print(f"    -> {len(groups)} shipment groups")

    print(f"[D] Verifying (tolerance={numeric_tolerance}) ...")
    verdicts = verify(groups, canonical_docs, numeric_tolerance=numeric_tolerance)
    _persist_json(
        [v.model_dump(mode="json") for v in verdicts],
        out_path / "verdicts.json",
    )
    passed = sum(1 for v in verdicts if v.verdict == "PASS")
    failed = sum(1 for v in verdicts if v.verdict == "FAIL")
    print(f"    -> {passed} PASS, {failed} FAIL")

    print("[E] Generating reports ...")
    results = report(verdicts, canonical_docs, str(out_path), groups=groups)
    print(f"    -> results.json + {len(verdicts)} reports written")

    print()
    print("=" * 50)
    print("EMAIL PIPELINE SUMMARY")
    print("=" * 50)
    print(f"  Documents from email: {len(raw_docs)}")
    print(f"  Canonical records   : {len(canonical_docs)}")
    print(f"  Shipment groups     : {len(groups)}")
    print(f"  Verdicts PASS       : {passed}")
    print(f"  Verdicts FAIL       : {failed}")
    print("=" * 50)

    return results


def run_agent_simulation(
    num_emails: int,
    out_dir: str,
    use_llm: bool,
    numeric_tolerance: float,
    mode: str = "existing",
    dry_run: bool = False,
) -> dict:
    """Agent simulation mode: agents send docs via email, then pipeline processes.

    Args:
        num_emails: Number of simulated emails to send.
        out_dir: Output directory for results.
        use_llm: Enable LLM fallback.
        numeric_tolerance: Numeric comparison tolerance.
        mode: "existing", "generated", or "mixed".
        dry_run: If True, simulate without sending emails.

    Returns:
        Pipeline results dict.
    """
    from docverify.agents.simulator import run_simulation

    print("=" * 50)
    print("AGENT SIMULATION MODE")
    print("=" * 50)

    # Step 1: Run simulation
    print(f"[SIM] Sending {num_emails} simulated emails (mode={mode}, dry_run={dry_run}) ...")
    sim_results = run_simulation(
        num_emails=num_emails,
        mode=mode,
        dry_run=dry_run,
    )

    sent = sum(1 for r in sim_results if r["status"] == "sent")
    failed = sum(1 for r in sim_results if r["status"] == "failed")
    print(f"    -> {sent} sent, {failed} failed")

    if dry_run:
        print("[SIM] Dry run — skipping pipeline processing")
        return {"simulation": sim_results, "pipeline": None}

    # Step 2: Wait for emails to arrive, then process
    import time
    print("[SIM] Waiting 5s for emails to arrive in inbox ...")
    time.sleep(5)

    print("[SIM] Running email pipeline ...")
    results = run_email_pipeline(out_dir, use_llm, numeric_tolerance)
    results["simulation"] = sim_results

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="docverify",
        description="Shipping document cross-reference verification engine",
    )
    parser.add_argument(
        "--corpus",
        type=str,
        default="data/corpus",
        help="Path to directory containing .docx/.xlsx files (default: data/corpus)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="data/out",
        help="Path to output directory for results (default: data/out)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Enable LLM fallback for extraction (requires LLM_PROVIDER + key)",
    )
    parser.add_argument(
        "--numeric-tolerance",
        type=float,
        default=0.0,
        help="Tolerance for numeric field comparisons (default: 0.0 = exact match)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Remove stale output directory before running (prevents ghost artifacts)",
    )
    # Phase 2 flags
    parser.add_argument(
        "--email-inbox",
        action="store_true",
        default=False,
        help="Ingest documents from email inbox (requires EMAIL_* env vars)",
    )
    parser.add_argument(
        "--simulate-agents",
        action="store_true",
        default=False,
        help="Run agent simulation -- agents send docs via email, then pipeline processes",  # BUG-035: em-dash replaced
    )
    parser.add_argument(
        "--num-emails",
        type=int,
        default=10,
        help="Number of simulated emails (with --simulate-agents, default: 10)",
    )
    parser.add_argument(
        "--sim-mode",
        type=str,
        choices=["existing", "generated", "mixed"],
        default="existing",
        help="Simulation document source (default: existing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate without sending emails (with --simulate-agents)",
    )

    args = parser.parse_args()

    # BUG-028: Validate numeric-tolerance is finite and non-negative
    import math
    if math.isnan(args.numeric_tolerance) or math.isinf(args.numeric_tolerance):
        print("Error: --numeric-tolerance must be a finite number", file=sys.stderr)
        sys.exit(1)
    if args.numeric_tolerance < 0:
        print("Error: --numeric-tolerance must be non-negative", file=sys.stderr)
        sys.exit(1)

    # BUG-027: Validate --num-emails is positive
    if args.num_emails < 1:
        print("Error: --num-emails must be at least 1", file=sys.stderr)
        sys.exit(1)

    # BUG-026: Validate ingestion mode flags are not conflicting
    if args.email_inbox and args.simulate_agents:
        print("Error: --email-inbox and --simulate-agents are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    try:
        if args.simulate_agents:
            run_agent_simulation(
                num_emails=args.num_emails,
                out_dir=args.out,
                use_llm=args.use_llm,
                numeric_tolerance=args.numeric_tolerance,
                mode=args.sim_mode,
                dry_run=args.dry_run,
            )
        elif args.email_inbox:
            run_email_pipeline(args.out, args.use_llm, args.numeric_tolerance)
        else:
            run_pipeline(args.corpus, args.out, args.use_llm, args.numeric_tolerance, clean=args.clean)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        print(f"Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
