"""Typed GitHub receipts and per-response pagination at the provider boundary."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GitHubPagination:
    next_page: int | None = None

    @classmethod
    def from_link(cls, value: str) -> GitHubPagination:
        for link in value.split(","):
            if 'rel="next"' not in link:
                continue
            target = link.split(";", 1)[0].strip().strip("<>")
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query)
            candidate = query.get("page", [""])[0]
            if candidate.isdigit():
                return cls(int(candidate))
        return cls()

    def next_after(self, page: int) -> int | None:
        return self.next_page if self.next_page is not None and self.next_page > page else None


@dataclass(frozen=True, slots=True)
class GitHubModelResponse[T]:
    status: int
    data: T
    pagination: GitHubPagination


@dataclass(frozen=True, slots=True)
class GitHubAcknowledgement:
    status: int
