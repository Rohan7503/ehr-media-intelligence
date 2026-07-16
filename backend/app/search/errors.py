"""Application exceptions for the search subsystem."""


class SearchError(Exception):
    """Base class for all search errors."""


class SearchValidationError(SearchError):
    """The search request or its filters are invalid (maps to HTTP 422)."""


class IndexUnavailableError(SearchError):
    """The vector index cannot be opened or is empty (maps to a service error)."""
