"""Signed Analysis MCP parent, isolated from all native Ghidra processing."""
from contextlib import asynccontextmanager
from fastmcp.tools import Tool
from hand_runtime.node_adapter import create_node_app, run_node_app
from .isolated_supervisor import IsolatedSupervisor


class MetadataTool(Tool):
    async def run(self, arguments):
        raise RuntimeError("Metadata-only tool cannot execute")


def create_app(spec):
    if spec.release.module != "reverse" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved non-root project Analysis placement required")
    supervisor = IsolatedSupervisor("reverse_hand.isolated_child", spec.limits.memory_bytes)

    @asynccontextmanager
    async def lifespan(_app):
        await supervisor.warmup()
        try:
            yield
        finally:
            await supervisor.close()

    def register_tools(mcp):
        catalogue = supervisor.catalogue
        if not isinstance(catalogue, list) or not 0 < len(catalogue) <= 512:
            raise ValueError("Actual bounded Analysis catalogue required")
        for item in catalogue:
            mcp.add_tool(MetadataTool.model_validate(item))

    return create_node_app(spec, register_tools=register_tools, execute=supervisor.call,
                           lifespan=lifespan, ready=supervisor.ready)


if __name__ == "__main__":
    run_node_app(create_app, "reverse")
