"""Provider repository visibility used by read-only public fallback admission."""

from typing import ClassVar, Literal, Self

from pydantic import BaseModel, Field, RootModel, StrictBool

from source_control.providers.github.history_views import (
    ActorSource,
    IdentitySource,
    VerificationSource,
)

from .pagination import PageQuery
from .requests import GitHubRequestBody, omit_unreported


class RepositoryVisibility(BaseModel):
    private: StrictBool

    @property
    def is_public(self) -> bool:
        return self.private is False


class GitObjectId(BaseModel):
    sha: str = Field(min_length=1)


class GitReferenceTarget(GitObjectId):
    type: str | None = None
    url: str | None = None


class GitReferenceRecord(BaseModel):
    object: GitReferenceTarget
    ref: str | None = None
    node_id: str | None = None
    url: str | None = None


class GitCommitRecord(BaseModel):
    sha: str = Field(min_length=1)
    message: str
    tree: GitObjectId
    parents: list[GitObjectId] = Field(default_factory=list)
    author: IdentitySource | None = None
    committer: IdentitySource | None = None


class GitSignatureRequest(BaseModel):
    name: str
    email: str
    date: str | None = None


class CommitAuthors(GitHubRequestBody):
    author: GitSignatureRequest | None = None
    committer: GitSignatureRequest | None = None

    def with_default_authors(self, signature: GitSignatureRequest) -> Self:
        return self.model_copy(
            update={"author": self.author or signature, "committer": self.committer or signature}
        )


class GitCommitCreate(CommitAuthors):
    message: str
    tree: str
    parents: list[str]


class GitReferenceUpdate(GitHubRequestBody):
    sha: str
    force: bool


class RepositoryPolicyRecord(BaseModel):
    default_branch: str | None = None


class BranchProtectionRecord(BaseModel):
    protected: StrictBool


class GitTreeEntryRecord(GitObjectId):
    path: str
    type: str
    mode: str
    size: int = 0


class GitTreeRecord(GitObjectId):
    tree: list[GitTreeEntryRecord]
    truncated: bool = False


class GitTreeChange(BaseModel):
    path: str
    mode: str
    type: Literal["blob"] = "blob"
    sha: str | None


class GitTreeCreate(GitHubRequestBody):
    # GitHub requires an explicit sha:null to delete an entry; omission is different.
    omit_null_fields: ClassVar[bool] = False
    base_tree: str
    tree: list[GitTreeChange]


class GitBlobCreate(GitHubRequestBody):
    content: str
    encoding: str


class RepositoryFileIdentity(GitObjectId):
    type: str


class BranchRecord(BranchProtectionRecord):
    name: str
    commit: GitObjectId
    protection_url: str | None = None


class BranchRecords(RootModel[list[BranchRecord]]):
    pass


class GitReferenceCreate(GitHubRequestBody):
    ref: str
    sha: str


class BranchRenameRequest(GitHubRequestBody):
    new_name: str


class ComparedFile(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int


class CommitFile(ComparedFile):
    patch: str | None = None


class CommitFiles(RootModel[list[CommitFile]]):
    pass


class CommitDetailsRecord(BaseModel):
    message: str
    tree: GitObjectId
    author: IdentitySource | None = None
    committer: IdentitySource | None = None
    verification: VerificationSource | None = None


class RepositoryCommitRecord(GitObjectId):
    commit: CommitDetailsRecord
    author: ActorSource | None = None
    committer: ActorSource | None = None
    parents: list[GitObjectId]
    files: list[CommitFile] = Field(default_factory=list)


class CommitRecords(RootModel[list[RepositoryCommitRecord]]):
    pass


class CommitQuery(PageQuery):
    sha: str | None = None
    path: str | None = None


class ComparisonRecord(BaseModel):
    status: str
    ahead_by: int
    behind_by: int
    total_commits: int
    files: list[CommitFile] = Field(default_factory=list)


class TagRecord(BaseModel):
    name: str
    commit: GitObjectId


class TagRecords(RootModel[list[TagRecord]]):
    pass


class AnnotatedTagCreate(GitHubRequestBody):
    tag: str
    message: str
    object: str
    type: Literal["commit"] = "commit"
    tagger: GitSignatureRequest | None = None

    def with_default_tagger(self, signature: GitSignatureRequest) -> Self:
        return self.model_copy(update={"tagger": self.tagger or signature})


class RepositoryMergeSettingsRecord(RepositoryPolicyRecord):
    delete_branch_on_merge: StrictBool


class RepositoryPushPermissions(BaseModel):
    admin: StrictBool | None = Field(default=None, exclude_if=omit_unreported)
    pull: StrictBool | None = Field(default=None, exclude_if=omit_unreported)
    triage: StrictBool | None = Field(default=None, exclude_if=omit_unreported)
    push: StrictBool | None = Field(default=None, exclude_if=omit_unreported)
    maintain: StrictBool | None = Field(default=None, exclude_if=omit_unreported)


class RepositoryRecord(RepositoryVisibility, RepositoryPolicyRecord):
    full_name: str = Field(min_length=1)
    archived: StrictBool = False
    fork: StrictBool = False
    permissions: RepositoryPushPermissions = Field(default_factory=RepositoryPushPermissions)


class RepositoryRecords(RootModel[list[RepositoryRecord]]):
    pass


class InstallationRepositoryRecords(BaseModel):
    repositories: list[RepositoryRecord]
