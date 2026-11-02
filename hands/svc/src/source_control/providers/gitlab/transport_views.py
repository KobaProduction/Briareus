"""Immutable transport results and pagination metadata for the GitLab adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GitLabRequestHeaders:
    fields: tuple[tuple[str, str], ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class GitLabModelResponse[T]:
    status: int
    data: T
    pagination: GitLabPagination


@dataclass(frozen=True, slots=True)
class GitLabAcknowledgement:
    status: int


@dataclass(frozen=True, slots=True)
class GitLabPagination:
    next_page: str
    total: int | None
    total_pages: int | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> GitLabPagination:
        fields = {key.casefold(): value for key, value in headers.items()}
        return cls(
            next_page=fields.get("x-next-page", ""),
            total=_header_integer(fields.get("x-total", "")),
            total_pages=_header_integer(fields.get("x-total-pages", "")),
        )


def _header_integer(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None
