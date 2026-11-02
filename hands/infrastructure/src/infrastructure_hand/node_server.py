"""Current-Core provider adapter with identity-bound reusable process isolation."""

from fastmcp import FastMCP
from mcp.types import CallToolRequestParams, CallToolResult

from hand_runtime.node_adapter import (
    _supervisor_lifespan,
    create_node_app,
    invocation_context,
    run_node_app,
)
from hand_runtime.node_boundary import EffectBoundary
from hand_runtime.provider_supervisor import ProviderSupervisor
from node_protocol import Deployment
from node_protocol.effect import NodeEffectPermit

from .invocation_accounts import InvocationAccounts
from .source_tools import register_source_tools


def create_app(spec: Deployment) -> EffectBoundary:
    if spec.release.module != "infrastructure" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved project provider deployment required")
    supervisor = ProviderSupervisor("infrastructure")

    def register_tools(mcp: FastMCP[None]) -> None:
        register_source_tools(mcp, InvocationAccounts([]))
        from .dispatch import SourceToolDispatch

        supervisor.tools = set(SourceToolDispatch(InvocationAccounts([])).tools)
        from hand_runtime.provider_operations import register_provider_operations

        register_provider_operations(mcp, "infrastructure")

    lifespan = _supervisor_lifespan(supervisor.warmup, supervisor.close)

    async def execute(call: CallToolRequestParams, permit: NodeEffectPermit) -> CallToolResult:
        return await supervisor.execute(call, permit, invocation_context())

    return create_node_app(
        spec,
        register_tools=register_tools,
        execute=execute,
        lifespan=lifespan,
        ready=supervisor.ready,
    )


if __name__ == "__main__":
    run_node_app(create_app, "infrastructure")
