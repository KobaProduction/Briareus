"""Exact GitLab inputs for the common Source Control operations."""

from typing import Annotated, ClassVar, Literal

from pydantic import Field

from source_control.operations import provider_tool
from source_control.providers.gitlab.models import GitLabCommitAction

from .contracts import SourceOperation, SourceParameters


class GitLabListAccounts(SourceParameters):
    operation: Literal["list_accounts"]
    operation_name: ClassVar[SourceOperation] = "list_accounts"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_accounts")


class GitLabAccountCapabilities(SourceParameters):
    operation: Literal["account_capabilities"]
    operation_name: ClassVar[SourceOperation] = "account_capabilities"
    tool_name: ClassVar[str] = provider_tool("gitlab", "account_capabilities")
    project: str = ""


class GitLabRepositoryStatus(SourceParameters):
    operation: Literal["repository_status"]
    operation_name: ClassVar[SourceOperation] = "repository_status"
    tool_name: ClassVar[str] = provider_tool("gitlab", "repository_status")
    project: str


class GitLabListRepositories(SourceParameters):
    operation: Literal["list_repositories"]
    operation_name: ClassVar[SourceOperation] = "list_repositories"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_repositories")
    search: str = ""
    membership: bool = True
    owned: bool = False
    min_access_level: int = 0
    page: int = 1
    per_page: int = 100


class GitLabReadFile(SourceParameters):
    operation: Literal["read_file"]
    operation_name: ClassVar[SourceOperation] = "read_file"
    tool_name: ClassVar[str] = provider_tool("gitlab", "read_file")
    project: str
    path: str
    ref: str = "main"


class GitLabWriteFile(SourceParameters):
    operation: Literal["write_file"]
    operation_name: ClassVar[SourceOperation] = "write_file"
    tool_name: ClassVar[str] = provider_tool("gitlab", "write_file")
    project: str
    path: str
    content: str
    branch: str
    commit_message: str
    last_commit_id: str = ""


class GitLabDeleteFile(SourceParameters):
    operation: Literal["delete_file"]
    operation_name: ClassVar[SourceOperation] = "delete_file"
    tool_name: ClassVar[str] = provider_tool("gitlab", "delete_file")
    project: str
    path: str
    branch: str
    commit_message: str
    last_commit_id: str = ""


class GitLabListBranches(SourceParameters):
    operation: Literal["list_branches"]
    operation_name: ClassVar[SourceOperation] = "list_branches"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_branches")
    project: str
    search: str = ""
    page: int = 1
    per_page: int = 100


class GitLabCreateBranch(SourceParameters):
    operation: Literal["create_branch"]
    operation_name: ClassVar[SourceOperation] = "create_branch"
    tool_name: ClassVar[str] = provider_tool("gitlab", "create_branch")
    project: str
    branch: str
    ref: str


class GitLabDeleteBranch(SourceParameters):
    operation: Literal["delete_branch"]
    operation_name: ClassVar[SourceOperation] = "delete_branch"
    tool_name: ClassVar[str] = provider_tool("gitlab", "delete_branch")
    project: str
    branch: str


class GitLabCompareRefs(SourceParameters):
    operation: Literal["compare_refs"]
    operation_name: ClassVar[SourceOperation] = "compare_refs"
    tool_name: ClassVar[str] = provider_tool("gitlab", "compare_refs")
    project: str
    from_ref: str
    to_ref: str
    straight: bool = False


class GitLabGetCommit(SourceParameters):
    operation: Literal["get_commit"]
    operation_name: ClassVar[SourceOperation] = "get_commit"
    tool_name: ClassVar[str] = provider_tool("gitlab", "get_commit")
    project: str
    sha: str


class GitLabListCommits(SourceParameters):
    operation: Literal["list_commits"]
    operation_name: ClassVar[SourceOperation] = "list_commits"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_commits")
    project: str
    ref: str = ""
    path: str = ""
    page: int = 1
    per_page: int = 100


class GitLabListTree(SourceParameters):
    operation: Literal["list_tree"]
    operation_name: ClassVar[SourceOperation] = "list_tree"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_tree")
    project: str
    path: str = ""
    ref: str = "main"
    recursive: bool = False
    page: int = 1
    per_page: int = 100


class GitLabSearchCode(SourceParameters):
    operation: Literal["search_code"]
    operation_name: ClassVar[SourceOperation] = "search_code"
    tool_name: ClassVar[str] = provider_tool("gitlab", "search_code")
    project: str
    search: str
    ref: str = ""
    page: int = 1
    per_page: int = 100


class GitLabCommitChanges(SourceParameters):
    operation: Literal["commit_changes"]
    operation_name: ClassVar[SourceOperation] = "commit_changes"
    tool_name: ClassVar[str] = provider_tool("gitlab", "commit_changes")
    project: str
    branch: str
    commit_message: str
    actions: list[GitLabCommitAction]
    start_branch: str = ""


class GitLabListIssues(SourceParameters):
    operation: Literal["list_issues"]
    operation_name: ClassVar[SourceOperation] = "list_issues"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_issues")
    project: str
    state: str = "opened"
    search: str = ""
    page: int = 1
    per_page: int = 100


class GitLabGetIssue(SourceParameters):
    operation: Literal["get_issue"]
    operation_name: ClassVar[SourceOperation] = "get_issue"
    tool_name: ClassVar[str] = provider_tool("gitlab", "get_issue")
    project: str
    iid: int


class GitLabCreateIssue(SourceParameters):
    operation: Literal["create_issue"]
    operation_name: ClassVar[SourceOperation] = "create_issue"
    tool_name: ClassVar[str] = provider_tool("gitlab", "create_issue")
    project: str
    title: str
    description: str = ""
    labels: list[str] | None = None


class GitLabUpdateIssue(SourceParameters):
    operation: Literal["update_issue"]
    operation_name: ClassVar[SourceOperation] = "update_issue"
    tool_name: ClassVar[str] = provider_tool("gitlab", "update_issue")
    project: str
    iid: int
    title: str | None = None
    description: str | None = None
    state_event: str | None = None
    labels: list[str] | None = None


class GitLabAddIssueComment(SourceParameters):
    operation: Literal["add_issue_comment"]
    operation_name: ClassVar[SourceOperation] = "add_issue_comment"
    tool_name: ClassVar[str] = provider_tool("gitlab", "add_issue_comment")
    project: str
    iid: int
    body: str


class GitLabListChanges(SourceParameters):
    operation: Literal["list_changes"]
    operation_name: ClassVar[SourceOperation] = "list_changes"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_changes")
    project: str
    state: str = "opened"
    source_branch: str = ""
    target_branch: str = ""
    page: int = 1
    per_page: int = 100


class GitLabGetChange(SourceParameters):
    operation: Literal["get_change"]
    operation_name: ClassVar[SourceOperation] = "get_change"
    tool_name: ClassVar[str] = provider_tool("gitlab", "get_change")
    project: str
    iid: int


class GitLabCreateChange(SourceParameters):
    operation: Literal["create_change"]
    operation_name: ClassVar[SourceOperation] = "create_change"
    tool_name: ClassVar[str] = provider_tool("gitlab", "create_change")
    project: str
    source_branch: str
    target_branch: str
    title: str
    delete_source_branch_after_merge: bool
    description: str = ""
    squash: bool = False
    draft: bool = False


class GitLabUpdateChange(SourceParameters):
    operation: Literal["update_change"]
    operation_name: ClassVar[SourceOperation] = "update_change"
    tool_name: ClassVar[str] = provider_tool("gitlab", "update_change")
    project: str
    iid: int
    title: str | None = None
    description: str | None = None
    state_event: str | None = None
    target_branch: str | None = None
    delete_source_branch_after_merge: bool | None = None
    squash: bool | None = None


class GitLabAddChangeComment(SourceParameters):
    operation: Literal["add_change_comment"]
    operation_name: ClassVar[SourceOperation] = "add_change_comment"
    tool_name: ClassVar[str] = provider_tool("gitlab", "add_change_comment")
    project: str
    iid: int
    body: str


class GitLabChangeFiles(SourceParameters):
    operation: Literal["change_files"]
    operation_name: ClassVar[SourceOperation] = "change_files"
    tool_name: ClassVar[str] = provider_tool("gitlab", "change_files")
    project: str
    iid: int
    page: int = 1
    per_page: int = 100


class GitLabMergeChange(SourceParameters):
    operation: Literal["merge_change"]
    operation_name: ClassVar[SourceOperation] = "merge_change"
    tool_name: ClassVar[str] = provider_tool("gitlab", "merge_change")
    project: str
    iid: int
    delete_source_branch_after_merge: bool
    sha: str = ""
    squash: bool | None = None
    merge_when_pipeline_succeeds: bool = False
    merge_commit_message: str = ""
    squash_commit_message: str = ""


class GitLabListRuns(SourceParameters):
    operation: Literal["list_runs"]
    operation_name: ClassVar[SourceOperation] = "list_runs"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_runs")
    project: str
    ref: str = ""
    status: str = ""
    page: int = 1
    per_page: int = 100


class GitLabListRunJobs(SourceParameters):
    operation: Literal["list_run_jobs"]
    operation_name: ClassVar[SourceOperation] = "list_run_jobs"
    tool_name: ClassVar[str] = provider_tool("gitlab", "list_run_jobs")
    project: str
    pipeline_id: int
    page: int = 1
    per_page: int = 100


class GitLabJobLog(SourceParameters):
    operation: Literal["job_log"]
    operation_name: ClassVar[SourceOperation] = "job_log"
    tool_name: ClassVar[str] = provider_tool("gitlab", "job_log")
    project: str
    job_id: int
    max_chars: int = 100000


class GitLabRetryRun(SourceParameters):
    operation: Literal["retry_run"]
    operation_name: ClassVar[SourceOperation] = "retry_run"
    tool_name: ClassVar[str] = provider_tool("gitlab", "retry_run")
    project: str
    pipeline_id: int


class GitLabCancelRun(SourceParameters):
    operation: Literal["cancel_run"]
    operation_name: ClassVar[SourceOperation] = "cancel_run"
    tool_name: ClassVar[str] = provider_tool("gitlab", "cancel_run")
    project: str
    pipeline_id: int


class GitLabAuthorizeLocalGit(SourceParameters):
    operation: Literal["authorize_local_git"]
    operation_name: ClassVar[SourceOperation] = "authorize_local_git"
    tool_name: ClassVar[str] = provider_tool("gitlab", "authorize_local_git")
    project: str
    destination: str
    remote: str = "origin"


class GitLabPushLocalGit(SourceParameters):
    operation: Literal["push_local_git"]
    operation_name: ClassVar[SourceOperation] = "push_local_git"
    tool_name: ClassVar[str] = provider_tool("gitlab", "push_local_git")
    project: str
    destination: str
    branch: str = ""
    remote: str = "origin"
    set_upstream: bool = True
    expected_remote_sha: str = ""


class GitLabCreateWorktree(SourceParameters):
    operation: Literal["create_worktree"]
    operation_name: ClassVar[SourceOperation] = "create_worktree"
    tool_name: ClassVar[str] = provider_tool("gitlab", "create_worktree")
    project: str
    destination: str
    branch: str
    ref: str = ""


type GitLabCommand = Annotated[
    GitLabListAccounts
    | GitLabAccountCapabilities
    | GitLabRepositoryStatus
    | GitLabListRepositories
    | GitLabReadFile
    | GitLabWriteFile
    | GitLabDeleteFile
    | GitLabListBranches
    | GitLabCreateBranch
    | GitLabDeleteBranch
    | GitLabCompareRefs
    | GitLabGetCommit
    | GitLabListCommits
    | GitLabListTree
    | GitLabSearchCode
    | GitLabCommitChanges
    | GitLabListIssues
    | GitLabGetIssue
    | GitLabCreateIssue
    | GitLabUpdateIssue
    | GitLabAddIssueComment
    | GitLabListChanges
    | GitLabGetChange
    | GitLabCreateChange
    | GitLabUpdateChange
    | GitLabAddChangeComment
    | GitLabChangeFiles
    | GitLabMergeChange
    | GitLabListRuns
    | GitLabListRunJobs
    | GitLabJobLog
    | GitLabRetryRun
    | GitLabCancelRun
    | GitLabAuthorizeLocalGit
    | GitLabPushLocalGit
    | GitLabCreateWorktree,
    Field(discriminator="operation"),
]


GITLAB_COMMANDS: tuple[type[SourceParameters], ...] = (
    GitLabListAccounts,
    GitLabAccountCapabilities,
    GitLabRepositoryStatus,
    GitLabListRepositories,
    GitLabReadFile,
    GitLabWriteFile,
    GitLabDeleteFile,
    GitLabListBranches,
    GitLabCreateBranch,
    GitLabDeleteBranch,
    GitLabCompareRefs,
    GitLabGetCommit,
    GitLabListCommits,
    GitLabListTree,
    GitLabSearchCode,
    GitLabCommitChanges,
    GitLabListIssues,
    GitLabGetIssue,
    GitLabCreateIssue,
    GitLabUpdateIssue,
    GitLabAddIssueComment,
    GitLabListChanges,
    GitLabGetChange,
    GitLabCreateChange,
    GitLabUpdateChange,
    GitLabAddChangeComment,
    GitLabChangeFiles,
    GitLabMergeChange,
    GitLabListRuns,
    GitLabListRunJobs,
    GitLabJobLog,
    GitLabRetryRun,
    GitLabCancelRun,
    GitLabAuthorizeLocalGit,
    GitLabPushLocalGit,
    GitLabCreateWorktree,
)
