"""Signed Analysis MCP parent, isolated from all native Ghidra processing."""

from fastmcp import FastMCP

from hand_runtime.node_adapter import _supervisor_lifespan, create_node_app, run_node_app
from hand_runtime.node_boundary import EffectBoundary
from node_protocol import Deployment

from .isolated_supervisor import IsolatedSupervisor


def create_app(spec: Deployment) -> EffectBoundary:
    if spec.release.module != "reverse" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved non-root project Analysis placement required")
    supervisor = IsolatedSupervisor("reverse_hand.isolated_child", spec.limits.memory_bytes)

    lifespan = _supervisor_lifespan(supervisor.warmup, supervisor.close)

    def register_tools(mcp: FastMCP[None]) -> None:
        catalogue = supervisor.catalogue
        if catalogue is None or not 0 < len(catalogue) <= 512:
            raise ValueError("Actual bounded Analysis catalogue required")
        for item in catalogue:
            mcp.add_tool(item)

    return create_node_app(
        spec,
        register_tools=register_tools,
        execute=supervisor.call,
        execute_human=supervisor.call,
        lifespan=lifespan,
        ready=supervisor.ready,
    )


if __name__ == "__main__":
    run_node_app(create_app, "reverse")
