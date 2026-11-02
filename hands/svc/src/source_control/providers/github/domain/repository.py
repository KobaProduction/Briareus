"""Immutable repository facts observed under the caller's provider identity."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepositoryMetadata:
    repository: str
    default_branch: str
    private: bool
    archived: bool
    fork: bool
