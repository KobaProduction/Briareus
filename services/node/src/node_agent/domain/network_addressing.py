"""Deterministic placement bridge allocation never shadows a control peer."""

import hashlib
from contextlib import suppress
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

Address = IPv4Address | IPv6Address
Network = IPv4Network | IPv6Network


class AddressConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BridgeAllocation:
    subnet: IPv4Network
    gateway: IPv4Address


def protected_addresses(
    controls: tuple[str, ...], registries: frozenset[str]
) -> tuple[Address, ...]:
    values = [ip_address(value) for value in controls]
    for registry in registries:
        # DNS registry addresses belong in the provisioned deny set.
        # No untrusted target is ever resolved during planning.
        with suppress(ValueError):
            values.append(ip_address(registry.rsplit(":", 1)[0]))
    if not values:
        raise AddressConflict("Execution network address conflict")
    return tuple(values)


def require_unshadowed(subnets: tuple[Network, ...], protected: tuple[Address, ...]) -> None:
    if any(
        address.version == subnet.version and address in subnet
        for subnet in subnets
        for address in protected
    ):
        raise AddressConflict("Execution network address conflict")


def bridge_allocation(
    name: str, occupied: tuple[Network, ...], protected: tuple[Address, ...]
) -> BridgeAllocation:
    start = int.from_bytes(hashlib.sha256(name.encode()).digest()[:2], "big") % 16384
    for offset in range(16384):
        index = (start + offset) % 16384
        subnet = IPv4Network(f"10.{64 + index // 256}.{index % 256}.0/24")
        if any(address.version == 4 and address in subnet for address in protected):
            continue
        if any(value.version == 4 and value.overlaps(subnet) for value in occupied):
            continue
        return BridgeAllocation(subnet, subnet.network_address + 1)
    raise AddressConflict("Execution network address conflict")
