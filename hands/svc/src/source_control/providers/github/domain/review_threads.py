"""Provider review conversations independent of their REST or GraphQL encoding."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThreadComment:
    id: str
    database_id: int | None
    author: str
    body: str
    created_at: str
    url: str


@dataclass(frozen=True, slots=True)
class ReviewThread:
    id: str
    resolved: bool
    outdated: bool
    path: str
    line: int | None
    start_line: int | None
    comments: tuple[ThreadComment, ...]
