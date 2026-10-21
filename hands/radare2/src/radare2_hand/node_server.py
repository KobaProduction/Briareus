"""Signed Node MCP parent; native parsing runs under a separate untrusted UID."""
from contextlib import asynccontextmanager
from hand_runtime.node_adapter import create_node_app, run_node_app
from .isolated_supervisor import IsolatedSupervisor
from .tools import register_tools


def create_app(spec):
    if spec.release.module != "radare2" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved non-root radare2 placement required")
    supervisor = IsolatedSupervisor("radare2_hand.isolated_child")

    @asynccontextmanager
    async def lifespan(_app):
        await supervisor.warmup()
        try:
            yield
        finally:
            await supervisor.close()

    return create_node_app(spec, register_tools=register_tools, execute=supervisor.call,
                           lifespan=lifespan, ready=supervisor.ready)


if __name__ == "__main__":
    run_node_app(create_app, "radare2")
