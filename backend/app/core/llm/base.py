"""The provider-independent LLM interface (ADR-0008). Agent/business
logic calls this, never a vendor SDK directly — Claude Code's
availability during development is not a dependency the running
application can assume.

Deliberately minimal (one method): every Milestone 5 consumer needs
structured output, nothing needs free-text completion yet, and
ADR-0008 explicitly warns against over-speculating the interface shape
before a real adapter exists to validate it against.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class LLMProviderError(Exception):
    """Raised on any failure to produce a valid structured response:
    network/transport error, a non-success response, or a response that
    doesn't parse/validate against the requested model. Callers (the
    orchestration layer's retry loop) catch this specifically — anything
    else propagates as a real bug, not a retryable provider failure.
    """


class LLMProvider(Protocol):
    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseT],
        timeout_seconds: float = 30.0,
    ) -> ResponseT:
        """Returns an instance of response_model, parsed and validated
        from the provider's output. Raises LLMProviderError on any
        failure — never returns a partially-valid or best-guess object.
        """
        ...
