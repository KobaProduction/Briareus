"""Public placement routing facts are constraints, never execution authority."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import Literal

_PRIVATE_NETWORKS = tuple(
    IPv4Network(prefix) for prefix in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def require_public_supervisor(module: str, profile: str, effective_uid: int) -> None:
    if module != "terminal" or profile != "public" or effective_uid != 0:
        raise ValueError("Trusted Node Terminal public profile required")


@dataclass(frozen=True, slots=True)
class PublicRouting:
    subnet: str
    gateway: str
    dns: tuple[str, ...]

    def __post_init__(self) -> None:
        network = IPv4Network(self.subnet, strict=True)
        gateway = IPv4Address(self.gateway)
        if str(network) != self.subnet or str(gateway) != self.gateway:
            raise ValueError("Canonical IPv4 routing facts required")
        if not 16 <= network.prefixlen <= 30 or not any(
            network.subnet_of(parent) for parent in _PRIVATE_NETWORKS
        ):
            raise ValueError("Approved private bridge and embedded DNS facts required")
        if (
            gateway not in network
            or gateway in {network.network_address, network.broadcast_address}
            or self.dns != ("127.0.0.11",)
        ):
            raise ValueError("Approved private bridge and embedded DNS facts required")


@dataclass(frozen=True, slots=True)
class IPv4Route:
    interface: str
    destination: IPv4Address
    gateway: IPv4Address
    mask: IPv4Address
    flags: int

    def kind(self, routing: PublicRouting) -> Literal["default", "connected"] | None:
        if self.interface == "lo" and self.destination.is_loopback and int(self.gateway) == 0:
            return None
        if self.interface != "eth0":
            raise ValueError("Unexpected network route interface")
        if (int(self.destination), int(self.mask), str(self.gateway), self.flags) == (
            0,
            0,
            routing.gateway,
            3,
        ):
            return "default"
        network = IPv4Network(routing.subnet)
        if (self.destination, str(self.mask), int(self.gateway), self.flags) == (
            network.network_address,
            str(network.netmask),
            0,
            1,
        ):
            return "connected"
        raise ValueError("Kernel routes do not match the controller's placement facts")


@dataclass(frozen=True, slots=True)
class KernelNetwork:
    interfaces: frozenset[str]
    ipv4_routes: tuple[IPv4Route, ...]
    ipv6_interfaces: tuple[str, ...]
    nameservers: tuple[tuple[str, ...], ...]

    def require(self, routing: PublicRouting) -> None:
        if self.interfaces != {"lo", "eth0"}:
            raise ValueError("One private worker bridge interface required")
        kinds = tuple(route.kind(routing) for route in self.ipv4_routes)
        observed = tuple(kind for kind in kinds if kind is not None)
        if len(observed) != len(set(observed)):
            raise ValueError("Duplicate public network route")
        if set(observed) != {"default", "connected"}:
            raise ValueError("Exact connected prefix and default gateway required")
        if any(interface != "lo" for interface in self.ipv6_interfaces):
            raise ValueError("Unexpected non-loopback IPv6 route")
        if self.nameservers != (("127.0.0.11",),):
            raise ValueError("Controller-selected Docker embedded DNS required")
