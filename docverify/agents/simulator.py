"""Agent simulation orchestrator.

Coordinates multiple agent personas sending shipping documents via email.
Can reuse existing synthetic docs from the corpus or generate new ones.
Runs in a loop to simulate mass incoming emails.

Usage:
    from docverify.agents.simulator import run_simulation

    # Simulate 10 emails using existing corpus docs
    run_simulation(num_emails=10, mode="existing")

    # Simulate 5 emails with freshly generated docs
    run_simulation(num_emails=5, mode="generated")

    # Mixed mode
    run_simulation(num_emails=20, mode="mixed")
"""

import os
import random
import time
from pathlib import Path

from docverify.utils import get_logger

logger = get_logger(__name__)

# Default paths
DEFAULT_CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "corpus")
DEFAULT_GENERATED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "generated")


def _get_corpus_files(corpus_dir: str) -> list[str]:
    """Get all .docx/.xlsx files from the corpus directory."""
    p = Path(corpus_dir)
    if not p.is_dir():
        return []
    return sorted([str(f) for f in p.iterdir() if f.suffix.lower() in (".docx", ".xlsx")])


def _group_corpus_by_shipment(corpus_dir: str) -> dict[str, list[str]]:
    """Group corpus files by their S{nn} shipment prefix."""
    files = _get_corpus_files(corpus_dir)
    groups: dict[str, list[str]] = {}
    for f in files:
        name = Path(f).name
        # Extract S{nn} prefix
        if name.startswith("S") and len(name) > 2 and name[1:3].isdigit():
            key = name[:3]
        else:
            key = "ungrouped"
        groups.setdefault(key, []).append(f)
    return groups


def _pick_existing_shipment(corpus_dir: str, rng: random.Random) -> list[str]:
    """Pick all docs from one random shipment in the corpus."""
    groups = _group_corpus_by_shipment(corpus_dir)
    if not groups:
        return []
    key = rng.choice(list(groups.keys()))
    return groups[key]


def _pick_random_docs(corpus_dir: str, rng: random.Random, count: int = 3) -> list[str]:
    """Pick random individual docs from the corpus."""
    files = _get_corpus_files(corpus_dir)
    if not files:
        return []
    count = min(count, len(files))
    return rng.sample(files, count)


def _generate_new_shipment(generated_dir: str, rng_seed: int) -> list[str]:
    """Generate a new shipment set and return file paths."""
    from docverify.agents.generator import generate_shipment_set

    shipment_dir = os.path.join(generated_dir, f"sim_{rng_seed}")
    result = generate_shipment_set(shipment_dir, rng_seed=rng_seed, inject_errors=False)
    return result["files"]


def run_simulation(
    num_emails: int = 10,
    mode: str = "mixed",
    corpus_dir: str | None = None,
    generated_dir: str | None = None,
    recipient: str | None = None,
    delay_seconds: float = 0.5,
    dry_run: bool = False,
    rng_seed: int | None = None,
) -> list[dict]:
    """Run the agent simulation — send shipping docs via email.

    Args:
        num_emails: Number of emails to send.
        mode: "existing" (reuse corpus), "generated" (create new), "mixed" (both).
        corpus_dir: Path to existing corpus. Defaults to data/corpus.
        generated_dir: Path for generated docs. Defaults to data/generated.
        recipient: Email recipient. Defaults to EMAIL_TO env var.
        delay_seconds: Delay between emails (rate limiting).
        dry_run: If True, log what would be sent without actually sending.
        rng_seed: Seed for reproducibility.

    Returns:
        List of dicts with email details (persona, files, subject, status).
    """
    from docverify.agents.personas import PERSONAS, AgentPersona

    corpus_dir = corpus_dir or DEFAULT_CORPUS_DIR
    generated_dir = generated_dir or DEFAULT_GENERATED_DIR
    recipient = recipient or os.environ.get("EMAIL_TO", "tomasborja21@gmail.com")

    rng = random.Random(rng_seed)
    # Resolve rng_seed to a concrete int for arithmetic (BUG-001)
    effective_seed = rng_seed if rng_seed is not None else rng.randint(0, 2**31)
    results = []

    logger.info("Starting simulation: %d emails, mode=%s", num_emails, mode)

    for i in range(num_emails):
        # Pick a persona
        persona: AgentPersona = rng.choice(PERSONAS)

        # Pick documents based on mode
        if mode == "existing":
            files = _pick_existing_shipment(corpus_dir, rng)
        elif mode == "generated":
            if dry_run:
                files = []  # BUG-031: don't create files on disk during dry-run
            else:
                files = _generate_new_shipment(generated_dir, rng_seed=effective_seed + i)
        elif mode == "mixed":
            if rng.random() < 0.6:
                files = _pick_existing_shipment(corpus_dir, rng)
            else:
                if dry_run:
                    files = []  # BUG-031: don't create files on disk during dry-run
                else:
                    files = _generate_new_shipment(generated_dir, rng_seed=effective_seed + i)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        if not files:
            logger.warning("No files available for email %d, skipping", i + 1)
            continue

        # Build shipment info for the email body
        doc_names = [Path(f).name for f in files]
        shipment_info = {"order_no": f"SIM-{rng.randint(10000, 99999)}"}

        subject = persona.email_subject(shipment_info)
        body = persona.email_body(doc_names, shipment_info)

        entry = {
            "email_num": i + 1,
            "persona": persona.name,
            "role": persona.role,
            "company": persona.company,
            "subject": subject,
            "files": files,
            "recipient": recipient,
            "status": "pending",
        }

        if dry_run:
            entry["status"] = "dry_run"
            logger.info("[DRY RUN] Email %d/%d: %s -> %s | %d file(s)",
                        i + 1, num_emails, persona.name, recipient, len(files))
        else:
            try:
                from docverify.email.sender import send_with_multiple_attachments
                send_with_multiple_attachments(
                    to=recipient,
                    subject=subject,
                    body=body,
                    file_paths=files,
                )
                entry["status"] = "sent"
                logger.info("[SENT] Email %d/%d: %s -> %s | %d file(s)",
                            i + 1, num_emails, persona.name, recipient, len(files))
            except Exception as e:
                entry["status"] = "failed"
                entry["error"] = str(e)
                logger.error("[FAILED] Email %d/%d: %s — %s",
                             i + 1, num_emails, persona.name, e)

        results.append(entry)

        # Rate limiting
        if delay_seconds > 0 and i < num_emails - 1:
            time.sleep(delay_seconds)

    # Summary
    sent = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")
    dry = sum(1 for r in results if r["status"] == "dry_run")

    logger.info("Simulation complete: %d sent, %d failed, %d dry_run", sent, failed, dry)

    return results


if __name__ == "__main__":
    import sys

    num = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    mode = sys.argv[2] if len(sys.argv) > 2 else "dry_run"

    results = run_simulation(
        num_emails=num,
        mode="existing",
        dry_run=(mode == "dry_run"),
    )

    for r in results:
        print(f"  [{r['status']}] {r['persona']} ({r['role']}) — {r['subject']}")
        for f in r["files"]:
            print(f"      {Path(f).name}")
