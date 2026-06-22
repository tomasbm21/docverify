"""Optional LLM fallback for field extraction.

OWNER: Agent 02 (Extraction)
Imported lazily — the engine runs without any LLM key.

Phase 2: Delegates to the unified LLM router (docverify.llm.router) which
supports Ollama (local), Anthropic, and Gemini. The provider is selected via
the LLM_PROVIDER env var.

PRIVACY CONSTRAINT: Raw document data must ONLY be sent to endpoints that
provide zero-retention / no-train guarantees. For local Ollama, this is
inherently satisfied. For cloud providers, use paid/no-train keys only.

This module:
- Delegates to docverify.llm.router.resolve_labels()
- Returns {} if no LLM provider is available.
- Never logs the prompt payload at INFO level.
- Sends only the minimal unresolved label + surrounding snippet, not the
  full document.
"""

from docverify.utils import get_logger

logger = get_logger(__name__)


def resolve(
    unresolved: list[str],
    context: str,
    model: str = "",  # ignored — provider is selected via LLM_PROVIDER env var
) -> dict[str, str]:
    """Ask the configured LLM to map unresolved field labels to canonical field names.

    Args:
        unresolved: List of raw label strings the synonym dict could not resolve.
        context: A small snippet of the document surrounding the unresolved labels
                 (NOT the full document text).
        model: Ignored (kept for backward compatibility).

    Returns:
        Dict mapping each unresolved label to a canonical field name string,
        or {} if the call cannot be made.
    """
    if not unresolved:
        return {}

    try:
        from docverify.llm.router import resolve_labels
        return resolve_labels(unresolved, context)
    except ImportError:
        logger.warning("LLM router not available — skipping LLM fallback")
        return {}
    except Exception:
        logger.warning("LLM fallback failed", exc_info=True)
        return {}


if __name__ == "__main__":
    print("docverify.extraction.llm_fallback — resolve() ready")
    print("Set LLM_PROVIDER and corresponding API key to enable.")
    print("Options: ollama (local), anthropic, gemini")
