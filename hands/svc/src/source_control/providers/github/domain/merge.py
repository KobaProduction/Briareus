"""An explicit source-branch choice is bound to one current same-repository PR head."""

from dataclasses import dataclass


class MergeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PullSnapshot:
    head_repository: str
    base_repository: str
    head_sha: str
    source_branch: str
    target_branch: str
    body: str
    delete_choice: bool | None

    def require_owned(self, repository: str, expected: str) -> None:
        if (
            self.head_repository.casefold() != repository.casefold()
            or self.base_repository.casefold() != repository.casefold()
        ):
            raise MergeError("cross-repository pull request merge is disabled")
        if not self.head_sha:
            raise MergeError("pull request head has no sha")
        if self.head_sha != expected:
            raise MergeError(
                f"pull request head changed: expected {expected}, found {self.head_sha}"
            )

    def require_source_distinct(self) -> None:
        if not self.source_branch or self.source_branch == self.target_branch:
            raise MergeError("Cannot delete merge target branch")


@dataclass(frozen=True, slots=True)
class RepositoryMergeSettings:
    default_branch: str
    delete_branch_on_merge: bool

    def require_choice(self, pull: PullSnapshot, *, delete: bool) -> None:
        if not delete and self.delete_branch_on_merge:
            raise MergeError(
                "Repository auto-delete conflicts with explicit keep choice; disable it first"
            )
        if delete and pull.source_branch == self.default_branch:
            raise MergeError("Cannot delete default branch")


def require_merge_request(delete: object, expected: str | None) -> None:
    if type(delete) is not bool:
        raise MergeError("Explicit keep/delete source branch choice required")
    if not expected:
        raise MergeError("expected_head_sha is required for merge")


def require_method(method: str) -> None:
    if method not in {"merge", "squash", "rebase"}:
        raise MergeError("merge_method must be merge, squash, or rebase")
