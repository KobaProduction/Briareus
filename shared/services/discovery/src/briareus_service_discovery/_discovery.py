import asyncio
import time
from datetime import UTC, datetime

import httpx
from briareus_service_catalog import BUILTIN_SERVICES, ServiceDefinition
from pydantic import ValidationError

from ._models import DiscoveredService, DiscoverySnapshot, ServiceHealth
from ._registry import ServiceRegistry


class ServiceDiscovery:
    """Registry-driven candidates are confirmed over the node's actual private network."""

    def __init__(
        self, registry: ServiceRegistry, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self.registry = registry
        self.client = client or httpx.AsyncClient(
            timeout=0.75, follow_redirects=False, trust_env=False
        )
        self.known = {service.id: service for service in BUILTIN_SERVICES}
        self._snapshot: DiscoverySnapshot | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(12)

    async def _probe(self, service: ServiceDefinition, *, registered: bool) -> DiscoveredService:
        connected = False
        async with self._slots:
            try:
                if registered:
                    response = await self.client.get(service.internal_origin + "/health/discovery")
                    response.raise_for_status()
                    health = ServiceHealth.model_validate_json(response.content)
                    connected = (
                        health.ready
                        and health.service == service
                        and health.environment == self.registry.environment
                    )
            except (httpx.HTTPError, ValidationError):
                pass
        return DiscoveredService(
            id=service.id,
            name=service.name,
            group=service.group,
            connected=connected,
            mcp_path=service.mcp_path,
        )

    async def snapshot(self, *, refresh: bool = False) -> DiscoverySnapshot:
        async with self._lock:
            if not refresh and self._snapshot is not None and time.monotonic() < self._expires:
                return self._snapshot
            inventory = await asyncio.to_thread(self.registry.inventory)
            active = await asyncio.to_thread(self.registry.active_services)
            self.known.update((service.id, service) for service in inventory)
            services = await asyncio.gather(
                *(
                    self._probe(service, registered=service.id in active)
                    for service in self.known.values()
                )
            )
            self._snapshot = DiscoverySnapshot(
                services=tuple(sorted(services, key=lambda service: (service.group, service.name))),
                checked_at=datetime.now(UTC),
            )
            self._expires = time.monotonic() + 5
            return self._snapshot

    async def close(self) -> None:
        await self.client.aclose()
        await asyncio.to_thread(self.registry.close)

    async def connected(self, service_id: str) -> bool:
        snapshot = await self.snapshot()
        return any(service.id == service_id and service.connected for service in snapshot.services)
