"""Application exceptions for the summarization pipeline."""


class SummarizationError(Exception):
    """Base class for all summarization errors."""


class SummarizationConfigError(SummarizationError):
    """Missing or invalid configuration (for example, no API key or model)."""


class ProviderError(SummarizationError):
    """The summary provider failed (auth, rate limit, or service error)."""


class MalformedResponseError(SummarizationError):
    """The provider returned a response that does not match the summary schema."""


class WordLimitError(SummarizationError):
    """A rendered summary exceeds the hard word limit."""


class BundleNotSummarizableError(SummarizationError):
    """The requested patient has no valid stored Bundle to summarize."""
