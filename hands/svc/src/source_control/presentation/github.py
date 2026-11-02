"""Exact GitHub inputs for the common Source Control operations."""

from typing import Annotated, ClassVar, Literal

from pydantic import Field

from source_control.operations import provider_tool
from source_control.providers.github.models import AtomicChange

from .contracts import SourceOperation, SourceParameters


class GitHubListAccounts(SourceParameters):
    operation: Literal["list_accounts"]
    operation_name: ClassVar[SourceOperation] = "list_accounts"
    tool_name: ClassVar[str] = provider_tool("github", "list_accounts")


class GitHubAccountCapabilities(SourceParameters):
    operation: Literal["account_capabilities"]
    operation_name: ClassVar[SourceOperation] = "account_capabilities"
    tool_name: ClassVar[str] = provider_tool("github", "account_capabilities")
    repository: str = ""


class GitHubRepositoryStatus(SourceParameters):
    operation: Literal["repository_status"]
    operation_name: ClassVar[SourceOperation] = "repository_status"
    tool_name: ClassVar[str] = provider_tool("github", "repository_status")
    repository: str


class GitHubListRepositories(SourceParameters):
    operation: Literal["list_repositories"]
    operation_name: ClassVar[SourceOperation] = "list_repositories"
    tool_name: ClassVar[str] = provider_tool("github", "list_repositories")


class GitHubReadFile(SourceParameters):
    operation: Literal["read_file"]
    operation_name: ClassVar[SourceOperation] = "read_file"
    tool_name: ClassVar[str] = provider_tool("github", "read_file")
    repository: str
    path: str
    ref: str | None = None


class GitHubWriteFile(SourceParameters):
    operation: Literal["write_file"]
    operation_name: ClassVar[SourceOperation] = "write_file"
    tool_name: ClassVar[str] = provider_tool("github", "write_file")
    repository: str
    path: str
    content: str
    message: str
    branch: str


class GitHubDeleteFile(SourceParameters):
    operation: Literal["delete_file"]
    operation_name: ClassVar[SourceOperation] = "delete_file"
    tool_name: ClassVar[str] = provider_tool("github", "delete_file")
    repository: str
    path: str
    message: str
    branch: str


class GitHubListBranches(SourceParameters):
    operation: Literal["list_branches"]
    operation_name: ClassVar[SourceOperation] = "list_branches"
    tool_name: ClassVar[str] = provider_tool("github", "list_branches")
    repository: str


class GitHubCreateBranch(SourceParameters):
    operation: Literal["create_branch"]
    operation_name: ClassVar[SourceOperation] = "create_branch"
    tool_name: ClassVar[str] = provider_tool("github", "create_branch")
    repository: str
    branch: str
    from_branch: str = "main"


class GitHubDeleteBranch(SourceParameters):
    operation: Literal["delete_branch"]
    operation_name: ClassVar[SourceOperation] = "delete_branch"
    tool_name: ClassVar[str] = provider_tool("github", "delete_branch")
    repository: str
    branch: str


class GitHubCompareRefs(SourceParameters):
    operation: Literal["compare_refs"]
    operation_name: ClassVar[SourceOperation] = "compare_refs"
    tool_name: ClassVar[str] = provider_tool("github", "compare_refs")
    repository: str
    base: str
    head: str


class GitHubGetCommit(SourceParameters):
    operation: Literal["get_commit"]
    operation_name: ClassVar[SourceOperation] = "get_commit"
    tool_name: ClassVar[str] = provider_tool("github", "get_commit")
    repository: str
    ref: str


class GitHubListCommits(SourceParameters):
    operation: Literal["list_commits"]
    operation_name: ClassVar[SourceOperation] = "list_commits"
    tool_name: ClassVar[str] = provider_tool("github", "list_commits")
    repository: str
    ref: str | None = None
    path: str | None = None
    per_page: int = 50
    page: int = 1


class GitHubListTree(SourceParameters):
    operation: Literal["list_tree"]
    operation_name: ClassVar[SourceOperation] = "list_tree"
    tool_name: ClassVar[str] = provider_tool("github", "list_tree")
    repository: str
    path: str = ""
    ref: str | None = None


class GitHubSearchCode(SourceParameters):
    operation: Literal["search_code"]
    operation_name: ClassVar[SourceOperation] = "search_code"
    tool_name: ClassVar[str] = provider_tool("github", "search_code")
    repository: str
    query: str
    per_page: int = 30
    page: int = 1


class GitHubCommitChanges(SourceParameters):
    operation: Literal["commit_changes"]
    operation_name: ClassVar[SourceOperation] = "commit_changes"
    tool_name: ClassVar[str] = provider_tool("github", "commit_changes")
    repository: str
    branch: str
    message: str
    changes: list[AtomicChange]
    expected_head_sha: str | None = None


class GitHubListIssues(SourceParameters):
    operation: Literal["list_issues"]
    operation_name: ClassVar[SourceOperation] = "list_issues"
    tool_name: ClassVar[str] = provider_tool("github", "list_issues")
    repository: str
    state: str = "open"
    per_page: int = 50
    page: int = 1


class GitHubGetIssue(SourceParameters):
    operation: Literal["get_issue"]
    operation_name: ClassVar[SourceOperation] = "get_issue"
    tool_name: ClassVar[str] = provider_tool("github", "get_issue")
    repository: str
    number: int


class GitHubCreateIssue(SourceParameters):
    operation: Literal["create_issue"]
    operation_name: ClassVar[SourceOperation] = "create_issue"
    tool_name: ClassVar[str] = provider_tool("github", "create_issue")
    repository: str
    title: str
    body: str = ""
    labels: list[str] | None = None


class GitHubUpdateIssue(SourceParameters):
    operation: Literal["update_issue"]
    operation_name: ClassVar[SourceOperation] = "update_issue"
    tool_name: ClassVar[str] = provider_tool("github", "update_issue")
    repository: str
    number: int
    title: str | None = None
    body: str | None = None
    state: str | None = None
    labels: list[str] | None = None


class GitHubAddIssueComment(SourceParameters):
    operation: Literal["add_issue_comment"]
    operation_name: ClassVar[SourceOperation] = "add_issue_comment"
    tool_name: ClassVar[str] = provider_tool("github", "add_issue_comment")
    repository: str
    number: int
    body: str


class GitHubListChanges(SourceParameters):
    operation: Literal["list_changes"]
    operation_name: ClassVar[SourceOperation] = "list_changes"
    tool_name: ClassVar[str] = provider_tool("github", "list_changes")
    repository: str
    state: str = "open"
    per_page: int = 50
    page: int = 1


class GitHubGetChange(SourceParameters):
    operation: Literal["get_change"]
    operation_name: ClassVar[SourceOperation] = "get_change"
    tool_name: ClassVar[str] = provider_tool("github", "get_change")
    repository: str
    number: int


class GitHubCreateChange(SourceParameters):
    operation: Literal["create_change"]
    operation_name: ClassVar[SourceOperation] = "create_change"
    tool_name: ClassVar[str] = provider_tool("github", "create_change")
    repository: str
    title: str
    head: str
    base: str
    delete_source_branch_after_merge: bool
    body: str = ""
    draft: bool = False


class GitHubUpdateChange(SourceParameters):
    operation: Literal["update_change"]
    operation_name: ClassVar[SourceOperation] = "update_change"
    tool_name: ClassVar[str] = provider_tool("github", "update_change")
    repository: str
    number: int
    title: str | None = None
    body: str | None = None
    state: str | None = None
    base: str | None = None


class GitHubAddChangeComment(SourceParameters):
    operation: Literal["add_change_comment"]
    operation_name: ClassVar[SourceOperation] = "add_change_comment"
    tool_name: ClassVar[str] = provider_tool("github", "add_change_comment")
    repository: str
    number: int
    body: str


class GitHubChangeFiles(SourceParameters):
    operation: Literal["change_files"]
    operation_name: ClassVar[SourceOperation] = "change_files"
    tool_name: ClassVar[str] = provider_tool("github", "change_files")
    repository: str
    number: int


class GitHubMergeChange(SourceParameters):
    operation: Literal["merge_change"]
    operation_name: ClassVar[SourceOperation] = "merge_change"
    tool_name: ClassVar[str] = provider_tool("github", "merge_change")
    repository: str
    number: int
    delete_source_branch_after_merge: bool
    merge_method: str = "squash"
    commit_title: str | None = None
    commit_message: str | None = None
    expected_head_sha: str | None = None


class GitHubListRuns(SourceParameters):
    operation: Literal["list_runs"]
    operation_name: ClassVar[SourceOperation] = "list_runs"
    tool_name: ClassVar[str] = provider_tool("github", "list_runs")
    repository: str
    branch: str | None = None
    status: str | None = None
    per_page: int = 30
    page: int = 1


class GitHubListRunJobs(SourceParameters):
    operation: Literal["list_run_jobs"]
    operation_name: ClassVar[SourceOperation] = "list_run_jobs"
    tool_name: ClassVar[str] = provider_tool("github", "list_run_jobs")
    repository: str
    run_id: int


class GitHubJobLog(SourceParameters):
    operation: Literal["job_log"]
    operation_name: ClassVar[SourceOperation] = "job_log"
    tool_name: ClassVar[str] = provider_tool("github", "job_log")
    repository: str
    job_id: int
    max_chars: int = 100000


class GitHubRetryRun(SourceParameters):
    operation: Literal["retry_run"]
    operation_name: ClassVar[SourceOperation] = "retry_run"
    tool_name: ClassVar[str] = provider_tool("github", "retry_run")
    repository: str
    run_id: int


class GitHubCancelRun(SourceParameters):
    operation: Literal["cancel_run"]
    operation_name: ClassVar[SourceOperation] = "cancel_run"
    tool_name: ClassVar[str] = provider_tool("github", "cancel_run")
    repository: str
    run_id: int


class GitHubAuthorizeLocalGit(SourceParameters):
    operation: Literal["authorize_local_git"]
    operation_name: ClassVar[SourceOperation] = "authorize_local_git"
    tool_name: ClassVar[str] = provider_tool("github", "authorize_local_git")
    repository: str
    destination: str
    remote: str = "origin"


class GitHubPushLocalGit(SourceParameters):
    operation: Literal["push_local_git"]
    operation_name: ClassVar[SourceOperation] = "push_local_git"
    tool_name: ClassVar[str] = provider_tool("github", "push_local_git")
    repository: str
    destination: str
    branch: str = ""
    remote: str = "origin"
    set_upstream: bool = True


class GitHubCreateWorktree(SourceParameters):
    operation: Literal["create_worktree"]
    operation_name: ClassVar[SourceOperation] = "create_worktree"
    tool_name: ClassVar[str] = provider_tool("github", "create_worktree")
    repository: str
    destination: str
    branch: str
    ref: str = ""


type GitHubCommand = Annotated[
    GitHubListAccounts
    | GitHubAccountCapabilities
    | GitHubRepositoryStatus
    | GitHubListRepositories
    | GitHubReadFile
    | GitHubWriteFile
    | GitHubDeleteFile
    | GitHubListBranches
    | GitHubCreateBranch
    | GitHubDeleteBranch
    | GitHubCompareRefs
    | GitHubGetCommit
    | GitHubListCommits
    | GitHubListTree
    | GitHubSearchCode
    | GitHubCommitChanges
    | GitHubListIssues
    | GitHubGetIssue
    | GitHubCreateIssue
    | GitHubUpdateIssue
    | GitHubAddIssueComment
    | GitHubListChanges
    | GitHubGetChange
    | GitHubCreateChange
    | GitHubUpdateChange
    | GitHubAddChangeComment
    | GitHubChangeFiles
    | GitHubMergeChange
    | GitHubListRuns
    | GitHubListRunJobs
    | GitHubJobLog
    | GitHubRetryRun
    | GitHubCancelRun
    | GitHubAuthorizeLocalGit
    | GitHubPushLocalGit
    | GitHubCreateWorktree,
    Field(discriminator="operation"),
]


GITHUB_COMMANDS: tuple[type[SourceParameters], ...] = (
    GitHubListAccounts,
    GitHubAccountCapabilities,
    GitHubRepositoryStatus,
    GitHubListRepositories,
    GitHubReadFile,
    GitHubWriteFile,
    GitHubDeleteFile,
    GitHubListBranches,
    GitHubCreateBranch,
    GitHubDeleteBranch,
    GitHubCompareRefs,
    GitHubGetCommit,
    GitHubListCommits,
    GitHubListTree,
    GitHubSearchCode,
    GitHubCommitChanges,
    GitHubListIssues,
    GitHubGetIssue,
    GitHubCreateIssue,
    GitHubUpdateIssue,
    GitHubAddIssueComment,
    GitHubListChanges,
    GitHubGetChange,
    GitHubCreateChange,
    GitHubUpdateChange,
    GitHubAddChangeComment,
    GitHubChangeFiles,
    GitHubMergeChange,
    GitHubListRuns,
    GitHubListRunJobs,
    GitHubJobLog,
    GitHubRetryRun,
    GitHubCancelRun,
    GitHubAuthorizeLocalGit,
    GitHubPushLocalGit,
    GitHubCreateWorktree,
)
