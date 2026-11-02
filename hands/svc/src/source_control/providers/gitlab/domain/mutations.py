"""Existing GitLab edit completeness and merge-request text rules."""

from dataclasses import dataclass
from typing import Literal

from .errors import GitLabError

CommitAction = Literal["create", "update", "delete", "move", "chmod"]


@dataclass(frozen=True, slots=True)
class CommitEdit:
    action: CommitAction
    file_path: str
    content: str | None
    previous_path: str | None

    def require_complete(self) -> None:
        if not self.file_path:
            raise ValueError("file_path must not be empty")
        if self.action in {"create", "update"} and self.content is None:
            raise ValueError(f"{self.action} actions require content")
        if self.action == "move" and not self.previous_path:
            raise ValueError("move actions require previous_path")


def merge_request_title(title: str, *, draft: bool) -> str:
    if draft and not title.lower().startswith(("draft:", "wip:")):
        return f"Draft: {title}"
    return title


def require_note_body(body: str) -> None:
    if not body.strip():
        raise GitLabError("merge request note body is required")


@dataclass(frozen=True, slots=True)
class MergeRequestUpdate:
    title: str | None
    description: str | None
    state_event: str | None
    target_branch: str | None
    remove_source_branch: bool | None
    squash: bool | None

    def require_changes(self) -> None:
        if not any(
            value is not None
            for value in (
                self.title,
                self.description,
                self.state_event,
                self.target_branch,
                self.remove_source_branch,
                self.squash,
            )
        ):
            raise GitLabError("at least one merge request field must be supplied")
