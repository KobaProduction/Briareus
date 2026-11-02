"""Shared native browser failure identity across owner-specific adapters."""


class BrowserError(RuntimeError):
    """Browser operation failed."""
