"""A scriptable, deterministic LLMProvider for tests — and only tests.
Never wired as a silent runtime default: an agent with no real provider
configured must fail loudly (docs/AGENTIC_ARCHITECTURE.md "Failure
handling: degrade gracefully to insufficient evidence, never
fabricate") rather than quietly return canned data in production.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from app.core.llm.base import LLMProviderError, ResponseT


@dataclass
class _Call:
    system_prompt: str
    user_prompt: str
    response_model: type[BaseModel]


class FakeLLMProvider:
    """Construct with a queue of responses (or exceptions) to return in
    order, one per call to complete_structured. Records every call made
    for test assertions.
    """

    def __init__(self, responses: list[BaseModel | Exception]):
        self._responses = list(responses)
        self.calls: list[_Call] = []

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseT],
        timeout_seconds: float = 30.0,
    ) -> ResponseT:
        self.calls.append(_Call(system_prompt, user_prompt, response_model))

        if not self._responses:
            raise LLMProviderError("FakeLLMProvider: no more scripted responses")

        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response

        if not isinstance(next_response, response_model):
            raise LLMProviderError(
                f"FakeLLMProvider: scripted response is {type(next_response).__name__}, "
                f"caller requested {response_model.__name__}"
            )
        return next_response
