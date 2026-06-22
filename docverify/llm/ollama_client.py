"""Ollama client -- local LLM via HTTP API.

Connects to Ollama at OLLAMA_BASE_URL (default http://localhost:11434).
No API key needed -- runs entirely on your local machine.
"""

import json
import os

import requests

from docverify.utils import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3"


def _get_config() -> tuple[str, str]:
    base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    return base_url, model


def complete(prompt: str, system: str | None = None, temperature: float = 0.0) -> str:
    """Send a completion request to Ollama.

    Args:
        prompt: The user prompt.
        system: Optional system prompt.
        temperature: Sampling temperature (0.0 = deterministic).

    Returns:
        The model's response text.

    Raises:
        ConnectionError: If Ollama is unreachable.
        RuntimeError: If the API returns an error.
    """
    base_url, model = _get_config()
    url = f"{base_url}/api/generate"

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system

    logger.debug("Ollama request to %s model=%s", base_url, model)

    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError(
            f"Cannot reach Ollama at {base_url}. "
            "Is it running? Start with: ollama serve"
        )
    except requests.HTTPError as e:
        raise RuntimeError(f"Ollama API error: {e}")

    data = resp.json()
    response_text = data.get("response", "")
    if not response_text:
        logger.warning("Ollama returned empty response")
    return response_text


def health_check() -> bool:
    """Check if Ollama is reachable and the model is available."""
    try:
        base_url, model = _get_config()
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        return any(model in m for m in models)
    except Exception:
        return False


if __name__ == "__main__":
    print("Testing Ollama connection...")
    if health_check():
        base_url, model = _get_config()
        print(f"  Connected to {base_url}, model '{model}' available")
        result = complete("Say 'hello' in one word.", temperature=0.0)
        print(f"  Test response: {result}")
    else:
        base_url, model = _get_config()
        print(f"  FAILED: Cannot reach Ollama at {base_url} or model '{model}' not found")
