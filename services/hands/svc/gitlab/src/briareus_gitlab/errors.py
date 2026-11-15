from __future__ import annotations

import logging

from fastmcp.exceptions import ToolError


class GitLabError(RuntimeError):
    pass


class GitLabRequestError(GitLabError, ToolError):
    """An expected caller argument rejection, not a GitLab service failure."""

    def __init__(self, message: str) -> None:
        ToolError.__init__(self, message, log_level=logging.WARNING)
