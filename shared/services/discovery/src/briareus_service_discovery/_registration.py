import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from briareus_service_catalog import ServiceDefinition
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from ._models import ServiceHealth
from ._registry import RegistrySettings, ServiceRegistry


def attach_service_discovery(
    app: Starlette,
    service: ServiceDefinition,
    *,
    ready: Callable[[], bool] | None = None,
) -> Starlette:
    previous = app.router.lifespan_context
    instance = uuid4().hex

    async def health(_request: Request) -> JSONResponse:
        value = ServiceHealth(
            service=service,
            environment=RegistrySettings().environment,
            ready=ready() if ready else True,
        )
        return JSONResponse(value.model_dump(mode="json"), status_code=200 if value.ready else 503)

    async def heartbeat(registry: ServiceRegistry, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.to_thread(registry.announce, service, instance)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5)

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        async with previous(application):
            registry = ServiceRegistry()
            stop = asyncio.Event()
            task = asyncio.create_task(
                heartbeat(registry, stop), name=f"service-register:{service.id}"
            )
            try:
                yield
            finally:
                stop.set()
                await task
                await asyncio.to_thread(registry.withdraw, service, instance)
                await asyncio.to_thread(registry.close)

    app.add_route("/health/discovery", health, methods=["GET"])
    app.router.lifespan_context = lifespan
    return app
