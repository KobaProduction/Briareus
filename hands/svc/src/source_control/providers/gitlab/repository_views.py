"""Named GitLab repository results using validated provider records."""

from dataclasses import dataclass

from pydantic import BaseModel

from .infrastructure.schemas.repository import (
    CodeMatch,
    Comparison,
    FileMutation,
    GitLabBranch,
    GitLabCommit,
    GitLabDiff,
    TreeEntry,
)


class RepositoryResult(BaseModel):
    profile_id: str
    project: str


class RepositoryFile(RepositoryResult):
    path: str
    ref: str
    blob_id: str
    commit_id: str
    last_commit_id: str
    size: int
    content: str


class RepositoryTree(RepositoryResult):
    items: list[TreeEntry]
    page: int
    per_page: int
    next_page: str


class RepositorySearch(RepositoryResult):
    results: list[CodeMatch]
    page: int
    per_page: int
    next_page: str


class RepositoryCommits(RepositoryResult):
    commits: list[GitLabCommit]
    next_page: str


class RepositoryCommit(RepositoryResult):
    commit: GitLabCommit
    diff: list[GitLabDiff]


class RepositoryFileWrite(RepositoryResult):
    path: str
    branch: str
    operation: str
    result: FileMutation | None


class RepositoryFileDelete(RepositoryResult):
    path: str
    branch: str
    result: FileMutation | None


class RepositoryActions(RepositoryResult):
    branch: str
    commit: GitLabCommit


class RepositoryBranches(RepositoryResult):
    branches: list[GitLabBranch]
    next_page: str


class RepositoryBranchCreated(RepositoryResult):
    branch: GitLabBranch


class RepositoryBranchDeleted(RepositoryResult):
    branch: str
    status: int
    deleted: bool


class RepositoryComparison(RepositoryResult):
    comparison: Comparison


@dataclass(frozen=True, slots=True)
class GitSignature:
    name: str
    email: str
