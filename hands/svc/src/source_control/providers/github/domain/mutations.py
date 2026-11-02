"""Copy/move plans preserve blob identity and reject conflicting paths before committing a tree."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class MutationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CopyItem:
    source_path: str
    destination_path: str
    mode: str | None = None

    def normalized(self) -> "CopyItem":
        source = "/".join(part for part in self.source_path.strip("/").split("/") if part)
        destination = "/".join(part for part in self.destination_path.strip("/").split("/") if part)
        if not source or not destination:
            raise MutationError("every copy requires source_path and destination_path")
        if source == destination:
            raise MutationError("source_path and destination_path must be different")
        return CopyItem(source, destination, self.mode)


@dataclass(frozen=True, slots=True)
class GitTreeEntry:
    path: str
    kind: str
    sha: str
    mode: str
    size: int

    def require_source(self, path: str) -> None:
        if self.kind != "blob":
            raise MutationError(f"source path is not a Git blob: {path}")
        if not self.sha or not self.mode:
            raise MutationError(f"source blob is missing sha or mode: {path}")


@dataclass(frozen=True, slots=True)
class TreeChange:
    path: str
    mode: str
    sha: str | None


@dataclass(frozen=True, slots=True)
class CopiedFile:
    source_path: str
    destination_path: str
    sha: str
    mode: str
    size: int


class CopyPlan:
    def __init__(self, operation: Literal["copy", "move"], *, overwrite: bool) -> None:
        self.operation = operation
        self.overwrite = overwrite
        self.destinations: set[str] = set()
        self.sources: set[str] = set()
        self.entries: list[TreeChange] = []
        self.processed: list[CopiedFile] = []

    def admit(self, item: CopyItem) -> CopyItem:
        normalized = item.normalized()
        if normalized.destination_path in self.destinations:
            raise MutationError(f"duplicate destination_path: {normalized.destination_path}")
        self.destinations.add(normalized.destination_path)
        if self.operation == "move":
            if normalized.source_path in self.sources:
                raise MutationError(f"duplicate move source_path: {normalized.source_path}")
            self.sources.add(normalized.source_path)
        return normalized

    def append(
        self, item: CopyItem, source: GitTreeEntry | None, destination: GitTreeEntry | None
    ) -> None:
        if source is None:
            raise MutationError(f"source path is not a Git blob: {item.source_path}")
        source.require_source(item.source_path)
        if destination is not None:
            if not self.overwrite:
                raise MutationError(f"destination_path already exists: {item.destination_path}")
            if destination.kind != "blob":
                raise MutationError(f"destination_path is not a blob: {item.destination_path}")
        mode = item.mode or source.mode
        self.entries.append(TreeChange(item.destination_path, mode, source.sha))
        if self.operation == "move":
            self.entries.append(TreeChange(item.source_path, source.mode, None))
        self.processed.append(
            CopiedFile(item.source_path, item.destination_path, source.sha, mode, source.size)
        )


def copy_operation(value: str) -> Literal["copy", "move"]:
    operation = value.strip().casefold()
    if operation == "copy":
        return "copy"
    if operation == "move":
        return "move"
    raise MutationError("operation must be 'copy' or 'move'")


@dataclass(frozen=True, slots=True)
class AtomicInput:
    operation: str
    path: str
    mode: str
    content: str | None
    content_base64: str | None
    source_path: str | None
    source_ref: str | None


@dataclass(frozen=True, slots=True)
class DiscussionChange:
    title: str | None
    body: str | None
    state: str | None

    def require_state(self) -> None:
        if self.state is not None and self.state not in {"open", "closed"}:
            raise MutationError("state must be open or closed")

    @property
    def has_changes(self) -> bool:
        return self.title is not None or self.body is not None or self.state is not None


@dataclass(frozen=True, slots=True)
class IssueChange(DiscussionChange):
    labels: tuple[str, ...] | None

    def require_valid(self) -> None:
        self.require_state()
        if not self.has_changes and self.labels is None:
            raise MutationError("no issue fields were supplied")


@dataclass(frozen=True, slots=True)
class PullChange(DiscussionChange):
    base: str | None

    def require_valid(self) -> None:
        self.require_state()
        if self.base is not None and ":" in self.base:
            raise MutationError("cross-repository pull requests are disabled")
        if not self.has_changes and self.base is None:
            raise MutationError("no pull request fields were supplied")


class ReviewEvent(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    COMMENT = "COMMENT"
