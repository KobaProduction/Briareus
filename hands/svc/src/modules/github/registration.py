"""Provider tool registration without legacy transport or credential initialization."""
from common.runtime_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, WRITE_EXTERNAL
from .account_tools import register_github_account_tools
from .github_actions_tools import register_github_actions_tools
from .github_collab_tools import register_github_collab_tools
from .github_core_tools import register_github_core_tools
from .github_review_tools import register_github_review_tools
from .github_reviewer_tools import register_github_reviewer_tools
from .github_tools import register_github_workflow_tools


def register_github_tools(mcp, context, runtime_policy) -> None:
    register_github_account_tools(
        mcp,
        context.list_accounts,
        context.account_capabilities,
        READ_EXTERNAL,
    )
    register_github_core_tools(
        mcp,
        context.client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
        runtime_policy,
    )
    register_github_workflow_tools(
        mcp,
        context.client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
    )
    register_github_review_tools(
        mcp,
        context.client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )
    register_github_collab_tools(
        mcp,
        context.client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )
    register_github_actions_tools(
        mcp,
        context.client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
    )
    register_github_reviewer_tools(
        mcp,
        context.client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )

