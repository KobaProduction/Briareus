"""Safe failure details for backend discovery and calls."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackendFailure:
    error_type: str
    message: str
    hint: str


def call_failure(error: Exception) -> BackendFailure:
    if isinstance(error, TimeoutError) or "timed out" in str(error).casefold():
        return BackendFailure(
            "MCP_BACKEND_TIMEOUT",
            "The backend call timed out.",
            "The outcome may be unknown. Inspect the backend result or job state before any retry.",
        )
    return BackendFailure(
        type(error).__name__,
        "The backend call failed; inspect redacted runtime diagnostics.",
        "",
    )


def tool_failure() -> BackendFailure:
    return BackendFailure(
        "MCP_BACKEND_TOOL_ERROR",
        "The backend tool reported an error.",
        "Check the operation outcome before any retry.",
    )
