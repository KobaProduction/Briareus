"""Signed Node ingress for real upstream Serena and project LSP processes."""
from contextlib import asynccontextmanager
from fastmcp.tools import Tool
from hand_runtime.node_adapter import create_node_app, run_node_app
from .supervisor import SerenaSupervisor
from hand_runtime.deferred_calls import register_deferred_tools


class MetadataTool(Tool):
    async def run(self, arguments):
        raise RuntimeError("Metadata-only tool cannot execute")


def create_app(spec):
    if spec.release.module != "serena" or spec.release.run_as != "1000:1000" or spec.workspace is None:
        raise ValueError("Approved project-scoped Serena placement required")
    configuration = spec.configuration.serena if spec.configuration is not None else None
    if configuration is not None and configuration.language_backend != "LSP":
        raise ValueError("Real LSP backend required")
    supervisor = SerenaSupervisor(configuration.project_path if configuration is not None else ".")

    @asynccontextmanager
    async def lifespan(_app):
        await supervisor.warmup()
        try:
            yield
        finally:
            await supervisor.close()

    def register_tools(mcp):
        for item in supervisor.catalogue:
            mcp.add_tool(MetadataTool.model_validate(item))
        register_deferred_tools(mcp,'serena')

    return create_node_app(spec, register_tools=register_tools, execute=supervisor.call,
                           lifespan=lifespan, ready=supervisor.ready)


if __name__ == "__main__":
    run_node_app(create_app, "serena")
