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

from common.runtime_policy_contracts import GitLabRuntimePolicy as GitLabRuntimePolicy
from source_control.providers.gitlab.workflow_descriptions import GitLabToolDescriptions

from .domain.workflow import GUIDANCE_TOOLS as GUIDANCE_TOOLS
from .domain.workflow import LOCAL_FIRST_GUIDANCE as LOCAL_FIRST_GUIDANCE
from .domain.workflow import LOCAL_GIT_DISABLED as LOCAL_GIT_DISABLED
from .domain.workflow import LOCAL_GIT_TOOLS as LOCAL_GIT_TOOLS
from .domain.workflow import REMOTE_SOURCE_MUTATION_DISABLED as REMOTE_SOURCE_MUTATION_DISABLED
from .domain.workflow import SOURCE_MUTATION_TOOLS as SOURCE_MUTATION_TOOLS
from .domain.workflow import SourceWorkflowPolicy as SourceWorkflowPolicy


class GitLabLocalFirstMiddleware(GitLabToolDescriptions):
    """Apply local-first guidance and source-write policy to GitLab repository tools."""

    def _description_prefix(self, tool_name: str, policy: GitLabRuntimePolicy) -> str:
        return self._policy(policy).description_prefix(tool_name)

    @staticmethod
    def _policy(policy: GitLabRuntimePolicy) -> SourceWorkflowPolicy:
        return SourceWorkflowPolicy(
            policy.local_first_guidance,
            policy.local_git_transport_enabled,
            policy.remote_source_mutations_enabled,
        )

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        policy = self.policy_provider()
        workflow = self._policy(policy)
        denial = workflow.denial(tool_name)
        if denial is not None:
            raise ToolError(denial)

        result = await call_next(context)
        if not workflow.adds_guidance(tool_name):
            return result

        content = [*result.content, mt.TextContent(type="text", text=LOCAL_FIRST_GUIDANCE)]
        meta = dict(result.meta or {})
        meta["koba/gitlab-workflow"] = {
            "local_first_guidance": True,
            "local_git_transport_enabled": policy.local_git_transport_enabled,
            "remote_source_mutations_enabled": policy.remote_source_mutations_enabled,
        }
        return result.model_copy(update={"content": content, "meta": meta})
