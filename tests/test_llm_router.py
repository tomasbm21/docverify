"""Tests for the unified LLM router."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestLLMRouter:
    """Test the LLM router provider selection and fallback."""

    def test_default_provider_is_ollama(self):
        """Default LLM_PROVIDER should be 'ollama'."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROVIDER", None)
            from docverify.llm.router import _get_provider
            assert _get_provider() == "ollama"

    def test_provider_selection(self):
        """LLM_PROVIDER env var selects the provider."""
        from docverify.llm.router import _get_provider

        for provider in ("ollama", "anthropic", "gemini"):
            with patch.dict(os.environ, {"LLM_PROVIDER": provider}):
                assert _get_provider() == provider

    def test_unknown_provider_falls_back(self):
        """Unknown provider falls back to ollama."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}):
            from docverify.llm.router import _get_provider
            assert _get_provider() == "ollama"

    def test_resolve_labels_empty_input(self):
        """Empty unresolved list returns empty dict."""
        from docverify.llm.router import resolve_labels
        assert resolve_labels([], "some context") == {}

    def test_resolve_labels_valid_response(self):
        """Router correctly parses valid JSON response from LLM."""
        from docverify.llm.router import resolve_labels

        mock_response = '{"Nr. Ordine": "order_no", "Peso Lordo": "gross_kg"}'
        with patch("docverify.llm.router.llm_complete", return_value=mock_response):
            result = resolve_labels(["Nr. Ordine", "Peso Lordo"], "context")
            assert result == {"Nr. Ordine": "order_no", "Peso Lordo": "gross_kg"}

    def test_resolve_labels_strips_markdown(self):
        """Router strips markdown fencing from LLM response."""
        from docverify.llm.router import resolve_labels

        mock_response = '```json\n{"Nr. Ordine": "order_no"}\n```'
        with patch("docverify.llm.router.llm_complete", return_value=mock_response):
            result = resolve_labels(["Nr. Ordine"], "context")
            assert result == {"Nr. Ordine": "order_no"}

    def test_resolve_labels_rejects_invalid_fields(self):
        """Router rejects values not in the valid canonical set."""
        from docverify.llm.router import resolve_labels

        mock_response = '{"label1": "not_a_real_field", "label2": "order_no"}'
        with patch("docverify.llm.router.llm_complete", return_value=mock_response):
            result = resolve_labels(["label1", "label2"], "context")
            assert result == {"label2": "order_no"}

    def test_resolve_labels_handles_llm_error(self):
        """Router returns empty dict on LLM failure."""
        from docverify.llm.router import resolve_labels

        with patch("docverify.llm.router.llm_complete", side_effect=ConnectionError("down")):
            result = resolve_labels(["label"], "context")
            assert result == {}

    def test_resolve_labels_handles_invalid_json(self):
        """Router returns empty dict on invalid JSON."""
        from docverify.llm.router import resolve_labels

        with patch("docverify.llm.router.llm_complete", return_value="not json"):
            result = resolve_labels(["label"], "context")
            assert result == {}


class TestOllamaClient:
    """Test the Ollama HTTP client."""

    def test_health_check_connection_error(self):
        """Health check returns False when Ollama is unreachable."""
        import requests as req_lib
        with patch("docverify.llm.ollama_client.requests.get",
                   side_effect=req_lib.ConnectionError("refused")):
            from docverify.llm.ollama_client import health_check
            assert health_check() is False

    def test_health_check_success(self):
        """Health check returns True when model is available."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3:latest"}]}

        with patch("docverify.llm.ollama_client.requests.get", return_value=mock_resp):
            from docverify.llm.ollama_client import health_check
            assert health_check() is True

    def test_complete_connection_error(self):
        """Complete raises ConnectionError when Ollama is unreachable."""
        import requests as req_lib
        with patch("docverify.llm.ollama_client.requests.post",
                   side_effect=req_lib.ConnectionError("refused")):
            from docverify.llm.ollama_client import complete
            with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
                complete("hello")

    def test_complete_success(self):
        """Complete returns response text on success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"response": "Hello! How can I help?"}

        with patch("docverify.llm.ollama_client.requests.post", return_value=mock_resp):
            from docverify.llm.ollama_client import complete
            result = complete("hello")
            assert result == "Hello! How can I help?"


class TestLLMFallback:
    """Test the updated llm_fallback module delegates to router."""

    def test_empty_unresolved_returns_empty(self):
        """Empty input returns empty dict."""
        from docverify.extraction.llm_fallback import resolve
        assert resolve([], "context") == {}

    def test_delegates_to_router(self):
        """llm_fallback.resolve() delegates to router.resolve_labels()."""
        from docverify.extraction.llm_fallback import resolve

        with patch("docverify.llm.router.resolve_labels",
                   return_value={"label": "order_no"}):
            result = resolve(["label"], "context")
            assert result == {"label": "order_no"}

    def test_handles_import_error(self):
        """Returns empty dict if router is not importable."""
        from docverify.extraction.llm_fallback import resolve

        with patch("docverify.llm.router.resolve_labels",
                   side_effect=ImportError("no module")):
            result = resolve(["label"], "context")
            assert result == {}
