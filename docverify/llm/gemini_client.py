"""Google Gemini client — cloud LLM.

Requires GEMINI_API_KEY env var (must be a paid/no-train key).
Refactored from the original llm_fallback.py.
"""

import os

from docverify.utils import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "gemini-2.0-flash"


def complete(prompt: str, system: str | None = None, temperature: float = 0.0) -> str:
    """Send a completion request to Google Gemini.

    Args:
        prompt: The user prompt.
        system: Optional system prompt (prepended to prompt for Gemini).
        temperature: Sampling temperature.

    Returns:
        The model's response text.

    Raises:
        ValueError: If GEMINI_API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not set. "
            "Must be a paid/no-train key."
        )

    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError(
            "google-generativeai not installed. Run: pip install google-generativeai"
        )

    genai.configure(api_key=api_key)

    # Gemini doesn't have a separate system param — prepend it to the prompt.
    full_prompt = prompt
    if system:
        full_prompt = f"{system}\n\n{prompt}"

    logger.debug("Gemini request model=%s", DEFAULT_MODEL)

    try:
        model = genai.GenerativeModel(DEFAULT_MODEL)
        response = model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=4096,
            ),
        )
        return response.text.strip()
    except Exception as e:
        raise RuntimeError(f"Gemini API error: {e}")


if __name__ == "__main__":
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        print("Testing Gemini connection...")
        result = complete("Say 'hello' in one word.", temperature=0.0)
        print(f"  Test response: {result}")
    else:
        print("GEMINI_API_KEY not set — skipping test")
