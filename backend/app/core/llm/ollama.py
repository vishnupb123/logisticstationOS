"""The first real LLMProvider adapter (ADR-0008 / Milestone 5): a local
Ollama server. Chosen by the project owner specifically for true
local-first operation — no API key, no cloud account, consistent with
the data layer's own principles (ADR-0001) extended to inference.

Ollama is not installed on every dev machine by default. This adapter's
request/response handling is verified against a mocked HTTP layer
(backend/tests/core/test_ollama_provider.py) — a live call against a
real running Ollama server has not been exercised; see HANDOFF.md. To
use it for real: install Ollama, `ollama pull <model>` matching
Settings.ollama_model, and run `ollama serve` (or let the app launch it)
before any agent that depends on this provider runs.
"""

import json

import httpx
from pydantic import ValidationError

from app.core.llm.base import LLMProviderError, ResponseT

_CHAT_PATH = "/api/chat"


class OllamaProvider:
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseT],
        timeout_seconds: float = 30.0,
    ) -> ResponseT:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Ollama's structured-output mode: constrains generation to
            # valid JSON matching this schema, rather than hoping a
            # prompt instruction alone produces parseable output.
            "format": response_model.model_json_schema(),
            "stream": False,
        }

        try:
            response = httpx.post(
                f"{self._base_url}{_CHAT_PATH}", json=payload, timeout=timeout_seconds
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama request failed: {exc}") from exc

        try:
            body = response.json()
            content = body["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, json.JSONDecodeError, ValueError) as exc:
            raise LLMProviderError(f"Ollama response was not valid JSON: {exc}") from exc

        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            raise LLMProviderError(
                f"Ollama response did not match {response_model.__name__}: {exc}"
            ) from exc
