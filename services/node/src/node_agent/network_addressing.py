"""Decode native IPAM records before applying the pure bridge plan."""

from ipaddress import ip_network

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .docker_engine import EngineFailure
from .domain.network_addressing import (
    Address,
    AddressConflict,
    Network,
    bridge_allocation,
    require_unshadowed,
)
from .domain.network_addressing import (
    protected_addresses as protected_plan,
)
from .infrastructure.docker_commands import IpamSubnet, NetworkIpam
from .infrastructure.docker_request import AddressingEngine


class NetworkAddresses(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)
    ipam: NetworkIpam = Field(default_factory=NetworkIpam, alias="IPAM")


def protected_addresses(engine: AddressingEngine) -> tuple[Address, ...]:
    try:
        return protected_plan(engine.control_addresses, engine.allowed_registries)
    except (AddressConflict, ValueError) as exc:
        raise EngineFailure("Execution network address conflict") from exc


def subnets(ipam: NetworkIpam) -> tuple[Network, ...]:
    return tuple(
        ip_network(config.subnet, strict=True)
        for config in ipam.configs or []
        if config.subnet
    )


def validate_network_addresses(engine: AddressingEngine, ipam: NetworkIpam) -> None:
    try:
        require_unshadowed(subnets(ipam), protected_addresses(engine))
    except (ValueError, ValidationError) as exc:
        raise EngineFailure("Execution network address conflict") from exc


async def bridge_ipam(engine: AddressingEngine, name: str) -> NetworkIpam:
    try:
        rows = TypeAdapter(list[NetworkAddresses]).validate_python(
            (await engine.request("GET", "/networks")).json()
        )
        if len(rows) > 4096:
            raise AddressConflict("Execution network address conflict")
        occupied = tuple(subnet for row in rows for subnet in subnets(row.ipam))
        allocation = bridge_allocation(name, occupied, protected_addresses(engine))
        return NetworkIpam(
            driver="default",
            configs=[IpamSubnet(subnet=str(allocation.subnet), gateway=str(allocation.gateway))],
        )
    except (ValueError, ValidationError) as exc:
        raise EngineFailure("Execution network address conflict") from exc
