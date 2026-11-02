"""Unavailable durable execution authority closes the application scenario."""


class JournalUnavailable(RuntimeError):
    """No current authenticated execution journal is available."""
