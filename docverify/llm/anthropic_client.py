"""Anthropic Claude client — cloud LLM via official SDK.

Requires ANTHROPIC_API_KEY env var.
"""

import os

from docverify.utils import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6-20250514"


def complete(prompt: str, system: str | None = None, temperature: float = 0.0) -> str:
    """Send a completion request to Anthropic Claude.

    Args:
        prompt: The user prompt.
        system: Optional system prompt.
        temperature: Sampling temperature.

    Returns:
        The model's response text.

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. "
            "Get one at https://console.anthropic.com/"
        )

    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)

    logger.debug("Anthropic request model=%s", DEFAULT_MODEL)

    try:
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": DEFAULT_MODEL,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)
        return response.content[0].text
    except Exception as e:
        raise RuntimeError(f"Anthropic API error: {e}")


if __name__ == "__main__":
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        print("Testing Anthropic connection...")
        result = complete("Say 'hello' in one word.", temperature=0.0)
        print(f"  Test response: {result}")
    else:
        print("ANTHROPIC_API_KEY not set — skipping test")
