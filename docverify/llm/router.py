"""Unified LLM router — switchable between Ollama, Anthropic, and Gemini.

Reads LLM_PROVIDER env var to select the backend:
  - "ollama"    → local Ollama at OLLAMA_BASE_URL (default)
  - "anthropic" → Anthropic Claude API
  - "gemini"    → Google Gemini API

Usage:
    from docverify.llm.router import llm_complete, resolve_labels

    response = llm_complete("What is 2+2?")
    mappings = resolve_labels(["Nr. Ordine", "Peso Lordo"], context_snippet)
"""

import json
import os

from docverify.utils import get_logger

logger = get_logger(__name__)

VALID_FIELDS = {
    "order_no", "bl_no", "reference", "container_no", "seal_no",
    "shipper", "consignee", "vessel", "voyage", "pol", "pod",
    "ship_date", "description", "lot", "cartons", "net_kg",
    "gross_kg", "unit_price", "units", "amount", "value",
    "currency", "invoice_no", "invoice_date", "buyer", "incoterm",
}


def _get_provider() -> str:
    """Read LLM_PROVIDER from env, default to 'ollama'."""
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in ("ollama", "anthropic", "gemini"):
        logger.warning("Unknown LLM_PROVIDER '%s', falling back to ollama", provider)
        return "ollama"
    return provider


def llm_complete(prompt: str, system: str | None = None, temperature: float = 0.0) -> str:
    """Send a completion request to the configured LLM provider.

    Args:
        prompt: The user prompt.
        system: Optional system prompt.
        temperature: Sampling temperature (0.0 = deterministic).

    Returns:
        The model's response text.
    """
    provider = _get_provider()
    logger.debug("LLM request via %s", provider)

    if provider == "ollama":
        from docverify.llm.ollama_client import complete
    elif provider == "anthropic":
        from docverify.llm.anthropic_client import complete
    elif provider == "gemini":
        from docverify.llm.gemini_client import complete
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return complete(prompt, system=system, temperature=temperature)


def resolve_labels(unresolved: list[str], context: str) -> dict[str, str]:
    """Ask the LLM to map unresolved field labels to canonical field names.

    This replaces the Gemini-specific resolve() in llm_fallback.py with a
    provider-agnostic version.

    Args:
        unresolved: List of raw label strings the synonym dict could not resolve.
        context: A small snippet of the document surrounding the unresolved labels.

    Returns:
        Dict mapping each unresolved label to a canonical field name.
    """
    if not unresolved:
        return {}

    system_prompt = (
        "You are a field-label mapper for shipping documents. "
        "Given a list of raw field labels and a small document snippet, "
        "map each label to ONE of these canonical fields: "
        + ", ".join(sorted(VALID_FIELDS)) + ". "
        "Respond with ONLY a JSON object mapping each raw label to its canonical field. "
        "If a label cannot be mapped, omit it. No explanation, no markdown, just JSON."
    )

    user_prompt = (
        f"Unresolved labels: {json.dumps(unresolved)}\n\n"
        f"Document snippet:\n{context}"
    )

    try:
        text = llm_complete(user_prompt, system=system_prompt, temperature=0.0)
    except Exception:
        logger.warning("LLM label resolution failed", exc_info=True)
        return {}

    # Strip markdown fencing if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            logger.warning("LLM returned non-dict for label resolution")
            return {}
        # Validate
        cleaned = {}
        for k, v in result.items():
            if isinstance(k, str) and isinstance(v, str) and v in VALID_FIELDS:
                cleaned[k] = v
        return cleaned
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for label resolution")
        return {}


def health_check() -> dict[str, bool]:
    """Check health of all configured LLM providers.

    Returns:
        Dict mapping provider name to True/False (reachable or not).
    """
    results = {}

    # Always check Ollama
    try:
        from docverify.llm.ollama_client import health_check as ollama_check
        results["ollama"] = ollama_check()
    except Exception:
        results["ollama"] = False

    # Check Anthropic (just verify key exists)
    results["anthropic"] = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    # Check Gemini (just verify key exists)
    results["gemini"] = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    return results


if __name__ == "__main__":
    print("LLM Router — Health Check")
    print(f"  Active provider: {_get_provider()}")
    print()
    for provider, healthy in health_check().items():
        status = "OK" if healthy else "UNAVAILABLE"
        print(f"  {provider}: {status}")
