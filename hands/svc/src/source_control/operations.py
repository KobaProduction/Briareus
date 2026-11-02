"""Public SC operation identifiers; Core reads permissions without provider SDKs."""

from dataclasses import dataclass
from typing import Literal

type SourceTarget = Literal["github", "gitlab"]
type SourceOperation = Literal[
    "list_accounts",
    "account_capabilities",
    "repository_status",
    "list_repositories",
    "read_file",
    "write_file",
    "delete_file",
    "list_branches",
    "create_branch",
    "delete_branch",
    "compare_refs",
    "get_commit",
    "list_commits",
    "list_tree",
    "search_code",
    "commit_changes",
    "list_issues",
    "get_issue",
    "create_issue",
    "update_issue",
    "add_issue_comment",
    "list_changes",
    "get_change",
    "create_change",
    "update_change",
    "add_change_comment",
    "change_files",
    "merge_change",
    "list_runs",
    "list_run_jobs",
    "job_log",
    "retry_run",
    "cancel_run",
    "authorize_local_git",
    "push_local_git",
    "create_worktree",
]


@dataclass(frozen=True, slots=True)
class OperationBinding:
    target: SourceTarget
    operation: SourceOperation
    tool: str


_OPERATION_BINDINGS = (
    OperationBinding("github", "list_accounts", "github_accounts"),
    OperationBinding("github", "account_capabilities", "github_account_capabilities"),
    OperationBinding("github", "repository_status", "github_agent_status"),
    OperationBinding("github", "list_repositories", "github_agent_list_repositories"),
    OperationBinding("github", "read_file", "github_agent_get_file"),
    OperationBinding("github", "write_file", "github_agent_put_file"),
    OperationBinding("github", "delete_file", "github_agent_delete_file"),
    OperationBinding("github", "list_branches", "github_agent_list_branches"),
    OperationBinding("github", "create_branch", "github_agent_create_branch"),
    OperationBinding("github", "delete_branch", "github_agent_delete_branch"),
    OperationBinding("github", "compare_refs", "github_agent_compare"),
    OperationBinding("github", "get_commit", "github_agent_get_commit"),
    OperationBinding("github", "list_commits", "github_agent_list_commits"),
    OperationBinding("github", "list_tree", "github_agent_list_directory"),
    OperationBinding("github", "search_code", "github_agent_search_code"),
    OperationBinding("github", "commit_changes", "github_agent_commit_files"),
    OperationBinding("github", "list_issues", "github_agent_list_issues"),
    OperationBinding("github", "get_issue", "github_agent_get_issue"),
    OperationBinding("github", "create_issue", "github_agent_create_issue"),
    OperationBinding("github", "update_issue", "github_agent_update_issue"),
    OperationBinding("github", "add_issue_comment", "github_agent_add_issue_comment"),
    OperationBinding("github", "list_changes", "github_agent_list_pull_requests"),
    OperationBinding("github", "get_change", "github_agent_get_pull_request"),
    OperationBinding("github", "create_change", "github_agent_create_pull_request"),
    OperationBinding("github", "update_change", "github_agent_update_pull_request"),
    OperationBinding("github", "add_change_comment", "github_agent_add_pull_comment"),
    OperationBinding("github", "change_files", "github_agent_pull_files"),
    OperationBinding("github", "merge_change", "github_reviewer_merge_pull_request"),
    OperationBinding("github", "list_runs", "github_agent_workflow_runs"),
    OperationBinding("github", "list_run_jobs", "github_agent_workflow_jobs"),
    OperationBinding("github", "job_log", "github_agent_workflow_job_log"),
    OperationBinding("github", "retry_run", "github_agent_rerun_workflow_run"),
    OperationBinding("github", "cancel_run", "github_agent_cancel_workflow_run"),
    OperationBinding("github", "authorize_local_git", "github_authorize_local_git"),
    OperationBinding("github", "push_local_git", "github_push_local_git"),
    OperationBinding("github", "create_worktree", "github_create_worktree"),
    OperationBinding("gitlab", "list_accounts", "accounts"),
    OperationBinding("gitlab", "account_capabilities", "account_capabilities"),
    OperationBinding("gitlab", "repository_status", "project_status"),
    OperationBinding("gitlab", "list_repositories", "list_projects"),
    OperationBinding("gitlab", "read_file", "get_file"),
    OperationBinding("gitlab", "write_file", "put_file"),
    OperationBinding("gitlab", "delete_file", "delete_file"),
    OperationBinding("gitlab", "list_branches", "list_branches"),
    OperationBinding("gitlab", "create_branch", "create_branch"),
    OperationBinding("gitlab", "delete_branch", "delete_branch"),
    OperationBinding("gitlab", "compare_refs", "compare"),
    OperationBinding("gitlab", "get_commit", "get_commit"),
    OperationBinding("gitlab", "list_commits", "list_commits"),
    OperationBinding("gitlab", "list_tree", "list_tree"),
    OperationBinding("gitlab", "search_code", "search_code"),
    OperationBinding("gitlab", "commit_changes", "commit_actions"),
    OperationBinding("gitlab", "list_issues", "list_issues"),
    OperationBinding("gitlab", "get_issue", "get_issue"),
    OperationBinding("gitlab", "create_issue", "create_issue"),
    OperationBinding("gitlab", "update_issue", "update_issue"),
    OperationBinding("gitlab", "add_issue_comment", "add_issue_note"),
    OperationBinding("gitlab", "list_changes", "list_merge_requests"),
    OperationBinding("gitlab", "get_change", "get_merge_request"),
    OperationBinding("gitlab", "create_change", "create_merge_request"),
    OperationBinding("gitlab", "update_change", "update_merge_request"),
    OperationBinding("gitlab", "add_change_comment", "add_merge_request_note"),
    OperationBinding("gitlab", "change_files", "list_merge_request_diffs"),
    OperationBinding("gitlab", "merge_change", "merge_merge_request"),
    OperationBinding("gitlab", "list_runs", "list_pipelines"),
    OperationBinding("gitlab", "list_run_jobs", "list_pipeline_jobs"),
    OperationBinding("gitlab", "job_log", "job_trace"),
    OperationBinding("gitlab", "retry_run", "retry_pipeline"),
    OperationBinding("gitlab", "cancel_run", "cancel_pipeline"),
    OperationBinding("gitlab", "authorize_local_git", "authorize_local_git"),
    OperationBinding("gitlab", "push_local_git", "push_local_git"),
    OperationBinding("gitlab", "create_worktree", "create_worktree"),
)


def provider_tool(target: SourceTarget, operation: SourceOperation) -> str:
    for binding in _OPERATION_BINDINGS:
        if binding.target == target and binding.operation == operation:
            return binding.tool
    raise ValueError("Unsupported Source Control target operation")
