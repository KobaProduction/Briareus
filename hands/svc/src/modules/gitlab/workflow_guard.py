from __future__ import annotations

from collections.abc import Callable as Callable
from collections.abc import Sequence as Sequence

import mcp.types as mt
from fastmcp.exceptions import ToolError as ToolError
from fastmcp.server.middleware import CallNext as CallNext
from fastmcp.server.middleware import Middleware as Middleware
from fastmcp.server.middleware import MiddlewareContext as MiddlewareContext
from fastmcp.tools import Tool as Tool
from fastmcp.tools import ToolResult as ToolResult

from service_runtime.runtime_policy_contracts import GitLabRuntimePolicy as GitLabRuntimePolicy
from source_control.providers.gitlab.workflow_descriptions import GitLabToolDescriptions

LOCAL_FIRST_GUIDANCE = (
    "Koba GitLab workflow: for substantial source changes, prefer one local-first cycle: "
    "checkout with mode='git' into the persistent Terminal workspace, edit and validate locally, "
    "commit locally, authorize the checkout, then publish once with push_local_git. "
    "Push to the requested branch if GitLab permits it; create a merge request only "
    "when repository rules require one or the user requests one. "
    "Avoid repeated per-file GitLab API mutations; issues, merge requests, notes and "
    "pipelines remain control-plane operations."
)
REMOTE_SOURCE_MUTATION_DISABLED = (
    "Remote GitLab source/history mutations are disabled by policy. Use checkout_repository with "
    "mode='git', perform source work in Terminal, authorize_local_git, and publish with "
    "push_local_git. Issues, merge requests, notes and pipeline controls remain available."
)
LOCAL_GIT_DISABLED = (
    "Local Git transport is disabled by policy. Enable it in Version Control → GitLab → Settings "
    "before authorizing or pushing a local checkout."
)
SOURCE_MUTATION_TOOLS = frozenset(
    {
        "put_file",
        "delete_file",
        "commit_actions",
        "create_branch",
        "delete_branch",
    }
)
LOCAL_GIT_TOOLS = frozenset({"authorize_local_git", "push_local_git"})
GUIDANCE_TOOLS = SOURCE_MUTATION_TOOLS | LOCAL_GIT_TOOLS | {"checkout_repository"}


class GitLabLocalFirstMiddleware(GitLabToolDescriptions):
    """Apply local-first guidance and source-write policy to GitLab repository tools."""

    def _description_prefix(self, tool_name: str, policy: GitLabRuntimePolicy) -> str:
        if tool_name in LOCAL_GIT_TOOLS and not policy.local_git_transport_enabled:
            return LOCAL_GIT_DISABLED + " "
        if tool_name == "checkout_repository" and policy.local_first_guidance:
            return (
                "Preferred entry point for substantial source work. Use mode='git', continue in "
                "Terminal, then authorize and push the local checkout. "
            )
        if tool_name in SOURCE_MUTATION_TOOLS:
            if not policy.remote_source_mutations_enabled:
                return REMOTE_SOURCE_MUTATION_DISABLED + " "
            if policy.local_first_guidance:
                return LOCAL_FIRST_GUIDANCE + " "
        return ""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        policy = self.policy_provider()
        if tool_name in SOURCE_MUTATION_TOOLS and not policy.remote_source_mutations_enabled:
            raise ToolError(REMOTE_SOURCE_MUTATION_DISABLED)
        if tool_name in LOCAL_GIT_TOOLS and not policy.local_git_transport_enabled:
            raise ToolError(LOCAL_GIT_DISABLED)

        result = await call_next(context)
        if not policy.local_first_guidance or tool_name not in GUIDANCE_TOOLS:
            return result

        content = [*result.content, mt.TextContent(type="text", text=LOCAL_FIRST_GUIDANCE)]
        meta = dict(result.meta or {})
        meta["koba/gitlab-workflow"] = {
            "local_first_guidance": True,
            "local_git_transport_enabled": policy.local_git_transport_enabled,
            "remote_source_mutations_enabled": policy.remote_source_mutations_enabled,
        }
        return result.model_copy(update={"content": content, "meta": meta})
