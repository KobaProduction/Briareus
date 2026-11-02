"""Narrow native daemon HTTP boundary; executors never receive this port."""

from typing import Protocol

import httpx

from .container_models import ContainerConfiguration
from .docker_commands import NetworkConnect, NetworkCreate, VolumeCreate


class DockerRequestPort(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        accepted: tuple[int, ...] = (200,),
        params: dict[str, str | int] | None = None,
        payload: ContainerConfiguration
        | NetworkCreate
        | NetworkConnect
        | VolumeCreate
        | None = None,
    ) -> httpx.Response: ...


class AddressingEngine(DockerRequestPort, Protocol):
    control_addresses: tuple[str, ...]
    allowed_registries: frozenset[str]
