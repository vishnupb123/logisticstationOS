import pytest
from pydantic import BaseModel

from app.core.llm.base import LLMProviderError
from app.core.llm.fake import FakeLLMProvider


class _Greeting(BaseModel):
    text: str


class _Other(BaseModel):
    value: int


def test_returns_scripted_responses_in_order():
    provider = FakeLLMProvider([_Greeting(text="hello"), _Greeting(text="world")])

    first = provider.complete_structured(
        system_prompt="s", user_prompt="u1", response_model=_Greeting
    )
    second = provider.complete_structured(
        system_prompt="s", user_prompt="u2", response_model=_Greeting
    )

    assert first.text == "hello"
    assert second.text == "world"


def test_records_every_call():
    provider = FakeLLMProvider([_Greeting(text="hi")])
    provider.complete_structured(system_prompt="sys", user_prompt="usr", response_model=_Greeting)

    assert len(provider.calls) == 1
    assert provider.calls[0].system_prompt == "sys"
    assert provider.calls[0].user_prompt == "usr"
    assert provider.calls[0].response_model is _Greeting


def test_raises_when_queue_is_exhausted():
    provider = FakeLLMProvider([_Greeting(text="only one")])
    provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Greeting)

    with pytest.raises(LLMProviderError):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Greeting)


def test_scripted_exception_is_raised():
    provider = FakeLLMProvider([LLMProviderError("simulated failure")])

    with pytest.raises(LLMProviderError, match="simulated failure"):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Greeting)


def test_mismatched_response_model_raises():
    provider = FakeLLMProvider([_Greeting(text="wrong type")])

    with pytest.raises(LLMProviderError, match="caller requested _Other"):
        provider.complete_structured(system_prompt="s", user_prompt="u", response_model=_Other)
