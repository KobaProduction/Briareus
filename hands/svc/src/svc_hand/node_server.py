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
from node_protocol import Deployment
from node_protocol.effect import NodeEffectPermit
from source_control.presentation.tools import register_source_control_tools

from .invocation_accounts import InvocationAccounts
from .source_supervisor import SourceProviderSupervisor
from .source_tools import register_source_tools


def create_app(spec: Deployment) -> EffectBoundary:
    if spec.release.module != "svc" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved project provider deployment required")
    supervisor = SourceProviderSupervisor()

    def register_tools(mcp: FastMCP[None]) -> None:
        register_source_tools(mcp, InvocationAccounts([]))
        from .dispatch import SourceToolDispatch

        dispatch = SourceToolDispatch(InvocationAccounts([]))
        register_source_control_tools(mcp, dispatch.call)
        supervisor.tools = set(dispatch.tools)
        from hand_runtime.provider_operations import register_provider_operations

        register_provider_operations(mcp, "svc")

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
    run_node_app(create_app, "svc")
