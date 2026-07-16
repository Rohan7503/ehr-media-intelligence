"""Focused test that inspects the Anthropic request arguments."""

from types import SimpleNamespace
from typing import Any

from anthropic.types import ToolUseBlock

from app.summarization.prompt import TOOL_NAME
from app.summarization.provider import DEFAULT_MAX_TOKENS, AnthropicSummaryProvider

_DRAFT = {
    "chief_concern": "Stable",
    "key_diagnoses": ["Not documented"],
    "recent_media_records": ["Not documented"],
    "flagged_anomalies": ["Not documented"],
    "confidence": "low",
    "source_resource_ids": ["res-1"],
}


class _StubMessages:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        block = ToolUseBlock(type="tool_use", id="t1", name=TOOL_NAME, input=_DRAFT)
        return SimpleNamespace(content=[block])


class _StubClient:
    def __init__(self) -> None:
        self.messages = _StubMessages()


def test_request_omits_unsupported_sampling_and_disables_thinking() -> None:
    client = _StubClient()
    provider = AnthropicSummaryProvider(
        api_key="unused",
        model="claude-sonnet-5",
        client=client,  # type: ignore[arg-type]
    )

    result = provider.generate(system="sys", user="usr")

    assert result == _DRAFT
    kwargs = client.messages.kwargs
    assert kwargs is not None
    # No unsupported sampling parameters are sent.
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs
    # Thinking is explicitly disabled (supported by the installed SDK).
    assert kwargs["thinking"] == {"type": "disabled"}
    # The configured model and bounded token limit are retained.
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["max_tokens"] == DEFAULT_MAX_TOKENS
