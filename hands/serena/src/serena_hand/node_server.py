"""Signed Node ingress for real upstream Serena and project LSP processes."""

from fastmcp import FastMCP

from hand_runtime.deferred_calls import register_deferred_tools
from hand_runtime.node_adapter import _supervisor_lifespan, create_node_app, run_node_app
from hand_runtime.node_boundary import EffectBoundary
from node_protocol import Deployment

from .supervisor import SerenaSupervisor


# The SDK base Tool retains the exact catalogue and has no executable run()
# implementation. The trusted Node parent owns all execution and authority.
def create_app(spec: Deployment) -> EffectBoundary:
    if (
        spec.release.module != "serena"
        or spec.release.run_as != "1000:1000"
        or spec.workspace is None
    ):
        raise ValueError("Approved project-scoped Serena placement required")
    configuration = spec.configuration.serena if spec.configuration is not None else None
    if configuration is not None and configuration.language_backend != "LSP":
        raise ValueError("Real LSP backend required")
    supervisor = SerenaSupervisor(configuration.project_path if configuration is not None else ".")

    lifespan = _supervisor_lifespan(supervisor.warmup, supervisor.close)

    def register_tools(mcp: FastMCP[None]) -> None:
        for item in supervisor.catalogue or ():
            mcp.add_tool(item)
        register_deferred_tools(mcp, "serena")

    return create_node_app(
        spec,
        register_tools=register_tools,
        execute=supervisor.call,
        lifespan=lifespan,
        ready=supervisor.ready,
    )


if __name__ == "__main__":
    run_node_app(create_app, "serena")
