"""Typed private dispatch of original provider callables; no second MCP server."""

from collections.abc import Awaitable
from collections.abc import Callable as Callable
from inspect import isawaitable

from mcp.types import CallToolRequestParams, CallToolResult, ToolAnnotations
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue as JsonSchemaValue

from hand_runtime.account_lease import InvocationAccounts
from hand_runtime.provider_results import provider_result
from hand_runtime.tool_binding import ValidatedInvocation, _SourceToolRegistration
from hand_runtime.tool_binding import bind_invocation as bind_invocation
from modules.github.workflow_guard import SOURCE_MUTATION_TOOLS as GH_MUTATIONS
from modules.gitlab.workflow_guard import LOCAL_GIT_TOOLS as GL_LOCAL_GIT
from modules.gitlab.workflow_guard import SOURCE_MUTATION_TOOLS as GL_MUTATIONS
from node_protocol.provider_context import InvocationPolicies
from source_control.presentation.tools import register_source_control_tools

from .application.admission import AdmitSourceTool, ToolEffects
from .domain.provider_policy import ProviderPolicy, SourceEffect
from .infrastructure.provider_policies import SourceProviderPolicies
from .source_tools import register_source_tools


def tool_effects(name: str) -> tuple[ToolEffects, ...]:
    effects: list[ToolEffects] = []
    if name in GH_MUTATIONS:
        effects.append(ToolEffects("github", (SourceEffect.REMOTE_MUTATION,)))
    if name in GL_MUTATIONS:
        effects.append(ToolEffects("gitlab", (SourceEffect.REMOTE_MUTATION,)))
    if name in GL_LOCAL_GIT | {"create_worktree", "checkout_repository"}:
        effects.append(ToolEffects("gitlab", (SourceEffect.LOCAL_GIT,)))
    if name in {
        "github_authorize_local_git",
        "github_push_local_git",
        "github_create_worktree",
        "github_checkout_repository",
    }:
        effects.append(ToolEffects("github", (SourceEffect.LOCAL_GIT,)))
    return tuple(effects)


class SourceToolDispatch(_SourceToolRegistration):
    def __init__(
        self, accounts: InvocationAccounts, policies: InvocationPolicies | None = None
    ) -> None:
        selected = SourceProviderPolicies.from_context(policies)
        self.github_policy, self.gitlab_policy = selected.github_runtime, selected.gitlab_runtime
        self.tools: dict[str, ValidatedInvocation[BaseModel | Awaitable[BaseModel]]] = {}
        self.annotations: dict[str, ToolAnnotations | None] = {}
        self.contexts = register_source_tools(self, accounts, selected)
        register_source_control_tools(self, self.call)
        self._context_clearers = tuple(context.clear for context in self.contexts)

    def configure(self, policies: InvocationPolicies | None) -> None:
        selected = SourceProviderPolicies.from_context(policies)
        self.github_policy, self.gitlab_policy = selected.github_runtime, selected.gitlab_runtime
        github, gitlab = self.contexts
        github.policy, github.runtime_policy = selected.github, selected.github_runtime
        gitlab.settings = selected.gitlab

    async def call(self, call: CallToolRequestParams) -> CallToolResult:
        name = call.name
        if name not in self.tools:
            raise ValueError("Unregistered provider tool")
        admission = AdmitSourceTool(
            ProviderPolicy(
                self.github_policy.remote_source_mutations_enabled,
                self.github_policy.local_git_transport_enabled,
            ),
            ProviderPolicy(
                self.gitlab_policy.remote_source_mutations_enabled,
                self.gitlab_policy.local_git_transport_enabled,
            ),
        )
        for request in tool_effects(name):
            admission.execute(request)
        result = self.tools[name](call)
        outcome = await result if isawaitable(result) else result
        wire = provider_result(outcome)
        structured = wire.structured_content
        if structured is not None and not isinstance(structured, dict):
            raise ValueError("Provider structured content must be an object")
        return wire
