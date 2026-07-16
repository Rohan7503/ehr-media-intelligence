"""Summary provider interface and the production Anthropic implementation.

The :class:`SummaryProvider` protocol lets tests inject a fake provider so no
network call or API key is needed. The production provider uses the installed
``anthropic`` SDK with a forced tool call for structured JSON output.

Safety: the API key and the full clinical prompt are never logged. Only one
retry is attempted, and only for a transient connection/timeout error, to
avoid uncontrolled API cost.
"""

from typing import Any, Protocol

import anthropic

from app.summarization.errors import (
    MalformedResponseError,
    ProviderError,
    SummarizationConfigError,
)
from app.summarization.prompt import TOOL_INPUT_SCHEMA, TOOL_NAME

#: Conservative default; the model is configurable via settings.
DEFAULT_MAX_TOKENS = 700


class SummaryProvider(Protocol):
    """Produces a structured summary draft from a system and user message."""

    def generate(self, *, system: str, user: str) -> dict[str, Any]:
        """Return the structured tool output as a plain dict."""
        ...


class AnthropicSummaryProvider:
    """Structured-output summary provider backed by the Anthropic SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._client = client

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise SummarizationConfigError(
                "ANTHROPIC_API_KEY is required to generate a new summary; "
                "set it in the environment or .env"
            )
        # max_retries=0: we control retries explicitly to bound API cost.
        self._client = anthropic.Anthropic(api_key=self._api_key, max_retries=0)
        return self._client

    def generate(self, *, system: str, user: str) -> dict[str, Any]:
        client = self._get_client()
        transient_retried = False
        while True:
            try:
                message = client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    # No explicit temperature: Sonnet 5 rejects non-default
                    # sampling parameters. Thinking is disabled for this short
                    # structured-output request (adaptive thinking is on by
                    # default otherwise).
                    thinking={"type": "disabled"},
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[
                        {
                            "name": TOOL_NAME,
                            "description": "Record the structured clinical summary.",
                            "input_schema": TOOL_INPUT_SCHEMA,
                        }
                    ],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                )
                return _extract_tool_input(message)
            except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
                if transient_retried:
                    raise ProviderError(f"Anthropic connection error: {exc}") from exc
                transient_retried = True
                continue
            except anthropic.AuthenticationError as exc:
                raise ProviderError("Anthropic authentication failed") from exc
            except anthropic.RateLimitError as exc:
                raise ProviderError("Anthropic rate limit exceeded") from exc
            except anthropic.APIStatusError as exc:
                raise ProviderError(f"Anthropic API error (status {exc.status_code})") from exc
            except anthropic.APIError as exc:
                raise ProviderError(f"Anthropic API error: {exc}") from exc


def _extract_tool_input(message: anthropic.types.Message) -> dict[str, Any]:
    """Pull the forced tool call's input dict out of the response."""
    for block in message.content:
        if isinstance(block, anthropic.types.ToolUseBlock) and isinstance(block.input, dict):
            return block.input
    raise MalformedResponseError("Anthropic response contained no structured tool output")
