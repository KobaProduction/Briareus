"""Stable provider rejection type shared by domain and transport adapters."""

from .domain.errors import GitLabError as GitLabError

__all__ = ["GitLabError"]
