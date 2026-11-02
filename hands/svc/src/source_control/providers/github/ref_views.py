"""Named GitHub ref/history results and the internal branch mutation decision."""

from dataclasses import dataclass

from pydantic import BaseModel

from .history_views import CommitIdentity, CommitSummary, CommitVerificationMaterial
from .infrastructure.schemas.repository import BranchRecord, GitReferenceRecord
from .infrastructure.schemas.repository import CommitFile as CommitFile
from .infrastructure.schemas.repository import ComparedFile as ComparedFile


class RepositoryResult(BaseModel):
    repository: str


@dataclass(frozen=True, slots=True)
class BranchMutationPolicy:
    repository: str
    branch: str
    exists: bool
    github_protected: bool
    bridge_reserved: bool
    mutation_allowed: bool
    mutation_denial_reason: str | None


class BranchSummary(BaseModel):
    name: str
    sha: str
    protected: bool
    github_protected: bool
    bridge_reserved: bool
    mutation_allowed: bool
    mutation_denial_reason: str | None


class TagSummary(BaseModel):
    name: str
    sha: str


class BranchList(RepositoryResult):
    branches: list[BranchSummary]


class BranchUpdate(RepositoryResult):
    branch: str
    sha: str
    result: GitReferenceRecord


class RepositoryComparison(RepositoryResult):
    base: str
    head: str
    status: str
    ahead_by: int
    behind_by: int
    total_commits: int
    files: list[ComparedFile]


class CommitList(RepositoryResult):
    commits: list[CommitSummary]
    page: int


class CommitView(RepositoryResult):
    sha: str
    message: str
    tree_sha: str
    author: CommitIdentity
    committer: CommitIdentity
    verification: CommitVerificationMaterial
    parents: list[str]
    files: list[CommitFile]


class BranchDeletion(RepositoryResult):
    branch: str
    deleted: bool


class BranchRename(RepositoryResult):
    old_branch: str
    new_branch: str
    result: BranchRecord


class TagList(RepositoryResult):
    tags: list[TagSummary]
    page: int


class TagCreation(RepositoryResult):
    tag: str
    target_sha: str
    annotated: bool


class TagDeletion(RepositoryResult):
    tag: str
    deleted: bool


class BranchResetPlan(RepositoryResult):
    branch: str
    previous_head_sha: str
    target_ref: str
    target_sha: str
    protected_branch_override: bool
    dry_run: bool


class BranchResetApplied(BranchResetPlan):
    result: GitReferenceRecord
