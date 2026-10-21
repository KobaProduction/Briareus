"""Current-Core provider adapter with identity-bound reusable process isolation."""
from contextlib import asynccontextmanager
from hand_runtime.node_adapter import create_node_app, invocation_context, run_node_app
from hand_runtime.provider_supervisor import ProviderSupervisor
from .source_tools import register_source_tools
from .invocation_accounts import InvocationAccounts


def create_app(spec):
    if spec.release.module != "infrastructure" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved project provider deployment required")
    supervisor = ProviderSupervisor("infrastructure")

    def register_tools(mcp):
        register_source_tools(mcp, InvocationAccounts([]))
        from .dispatch import SourceToolDispatch
        supervisor.tools=set(SourceToolDispatch(InvocationAccounts([])).tools)
        from hand_runtime.provider_operations import register_provider_operations
        register_provider_operations(mcp,"infrastructure")

    @asynccontextmanager
    async def lifespan(_app):
        await supervisor.warmup()
        try:
            yield
        finally:
            await supervisor.close()

    async def execute(name, arguments, permit):
        return await supervisor.execute(name, arguments, permit, invocation_context())

    return create_node_app(spec, register_tools=register_tools, execute=execute,
        lifespan=lifespan, ready=supervisor.ready)


if __name__ == "__main__":
    run_node_app(create_app, "infrastructure")
