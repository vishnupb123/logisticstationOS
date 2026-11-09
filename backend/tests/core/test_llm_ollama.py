"""Ollama isn't installed on this machine (docs/OPEN_QUESTIONS.md) — these
tests verify OllamaProvider's request/response handling against a
mocked HTTP layer, not a live server. No new test dependency: httpx.post
is monkeypatched directly.
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.llm.base import LLMProviderError
from app.core.llm.ollama import OllamaProvider


class _Finding(BaseModel):
    summary: str
    confidence: float


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self._json_body = json_body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("POST", "http://x"), response=self
            )

    def json(self) -> dict:
        return self._json_body


def _ollama_success_response(content: dict) -> _FakeResponse:
    return _FakeResponse(200, {"message": {"role": "assistant", "content": json.dumps(content)}})


def test_sends_model_messages_and_json_schema_format(monkeypatch):
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _ollama_success_response({"summary": "ok", "confidence": 0.9})

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")
    result = provider.complete_structured(
        system_prompt="You are a flow intelligence agent.",
        user_prompt="Jackpot volume is elevated.",
        response_model=_Finding,
        timeout_seconds=15,
    )

    assert result == _Finding(summary="ok", confidence=0.9)
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "llama3.1"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "You are a flow intelligence agent."},
        {"role": "user", "content": "Jackpot volume is elevated."},
    ]
    assert captured["json"]["format"] == _Finding.model_json_schema()
    assert captured["json"]["stream"] is False
    assert captured["timeout"] == 15


def test_strips_trailing_slash_from_base_url(monkeypatch):
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        return _ollama_success_response({"summary": "ok", "confidence": 0.5})

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider(base_url="http://localhost:11434/", model="llama3.1")
    provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Finding)

    assert captured["url"] == "http://localhost:11434/api/chat"


def test_network_error_raises_llm_provider_error(monkeypatch):
    def fake_post(url, *, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")
    with pytest.raises(LLMProviderError, match="Ollama request failed"):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Finding)


def test_non_success_status_raises_llm_provider_error(monkeypatch):
    def fake_post(url, *, json, timeout):
        return _FakeResponse(500, {})

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")
    with pytest.raises(LLMProviderError, match="Ollama request failed"):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Finding)


def test_non_json_content_raises_llm_provider_error(monkeypatch):
    def fake_post(url, *, json, timeout):
        return _FakeResponse(200, {"message": {"content": "not json"}})

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")
    with pytest.raises(LLMProviderError, match="not valid JSON"):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Finding)


def test_json_not_matching_schema_raises_llm_provider_error(monkeypatch):
    def fake_post(url, *, json, timeout):
        return _ollama_success_response({"summary": "ok"})  # missing required 'confidence'

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")
    with pytest.raises(LLMProviderError, match="did not match _Finding"):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Finding)
