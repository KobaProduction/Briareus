"""GitLab repository schemas shared by file, branch, commit and review adapters."""

from pydantic import BaseModel, ConfigDict, Field, RootModel

from source_control.providers.gitlab.models import GitLabCommitAction

from .pagination import PageQuery
from .pipelines import PipelineSummary


class CommitStats(BaseModel):
    additions: int
    deletions: int
    total: int


class GitLabCommit(BaseModel):
    id: str
    short_id: str
    title: str
    message: str
    author_name: str
    author_email: str
    authored_date: str
    committer_name: str
    committer_email: str
    committed_date: str
    created_at: str | None = None
    parent_ids: list[str] = Field(default_factory=list)
    web_url: str | None = None

    last_pipeline: PipelineSummary | None = None
    stats: CommitStats | None = None
    status: str | None = None


class GitLabDiff(BaseModel):
    diff: str
    new_path: str
    old_path: str
    a_mode: str
    b_mode: str
    new_file: bool
    renamed_file: bool
    deleted_file: bool
    generated_file: bool | None = None
    collapsed: bool | None = None
    too_large: bool | None = None


class GitLabBranch(BaseModel):
    name: str
    commit: GitLabCommit
    merged: bool
    protected: bool
    default: bool
    developers_can_push: bool = False
    developers_can_merge: bool = False
    can_push: bool = False
    web_url: str | None = None


class GitLabFile(BaseModel):
    file_path: str
    file_name: str
    size: int
    encoding: str
    content: str
    ref: str
    blob_id: str
    commit_id: str
    last_commit_id: str
    execute_filemode: bool = False
    content_sha256: str | None = None


class TreeEntry(BaseModel):
    id: str
    name: str
    type: str
    path: str
    mode: str


class CodeMatch(BaseModel):
    basename: str | None = None
    data: str
    path: str
    filename: str
    id: int | None = None
    ref: str | None = None
    startline: int
    project_id: int | None = None


class Comparison(BaseModel):
    commit: GitLabCommit
    commits: list[GitLabCommit]
    diffs: list[GitLabDiff]
    compare_timeout: bool
    compare_same_ref: bool
    web_url: str | None = None


class FileMutation(BaseModel):
    file_path: str
    branch: str


class TreeRecords(RootModel[list[TreeEntry]]):
    pass


class CodeMatches(RootModel[list[CodeMatch]]):
    pass


class CommitRecords(RootModel[list[GitLabCommit]]):
    pass


class DiffRecords(RootModel[list[GitLabDiff]]):
    pass


class BranchRecords(RootModel[list[GitLabBranch]]):
    pass


class RefQuery(BaseModel):
    ref: str


class TreeQuery(PageQuery):
    path: str | None
    ref: str
    recursive: bool


class CodeSearchQuery(PageQuery):
    scope: str = "blobs"
    search: str
    ref: str | None


class CommitQuery(PageQuery):
    ref_name: str | None
    path: str | None


class BranchQuery(PageQuery):
    search: str | None


class BranchCreate(BaseModel):
    branch: str
    ref: str


class FileDelete(BaseModel):
    branch: str
    commit_message: str
    last_commit_id: str | None = None


class FileWrite(FileDelete):
    content: str


class CommitActions(BaseModel):
    branch: str
    commit_message: str
    actions: list[GitLabCommitAction]
    start_branch: str | None = None


class CompareQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_ref: str = Field(alias="from")
    to: str
    straight: bool
