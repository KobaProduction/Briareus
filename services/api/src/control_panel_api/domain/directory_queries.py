"""Owner-directory paging preserves an omitted parameter separately from explicit null."""

from dataclasses import dataclass
from enum import Enum


class Unspecified(Enum):
    VALUE = "unspecified"


UNSPECIFIED = Unspecified.VALUE


@dataclass(frozen=True, slots=True)
class DirectoryPageSelection:
    cursor: str | Unspecified | None = UNSPECIFIED
    limit: int | Unspecified = UNSPECIFIED
