"""Analyzer composition root; authentication remains at the node Gateway."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from starlette.applications import Starlette

from .provider import Radare2Provider

_management = management_client(ControlPanelClientSettings())
mcp = build_private_mcp("radare2", _management)
provider = Radare2Provider()
mcp.add_provider(provider)
app = private_http_app(mcp, PrivateRuntimeSettings())
_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application: Starlette) -> AsyncIterator[None]:
    async with _lifespan(application):
        try:
            yield
        finally:
            await provider.pool.close()


app.router.lifespan_context = lifespan
