"""Parse Linux routing observations without deciding placement permissions."""

from ipaddress import IPv4Address
from pathlib import Path

from terminal_hand.domain.public_network import IPv4Route, KernelNetwork


def ipv4_route(line: str) -> IPv4Route:
    parts = line.split()
    if len(parts) < 11:
        raise ValueError("Unexpected kernel route format")
    destination, gateway, mask = (
        IPv4Address(int(parts[index], 16).to_bytes(4, "little")) for index in (1, 2, 7)
    )
    return IPv4Route(parts[0], destination, gateway, mask, int(parts[3], 16))


def ipv6_interface(line: str) -> str:
    parts = line.split()
    if len(parts) < 10:
        raise ValueError("Unexpected non-loopback IPv6 route")
    return parts[-1]


def kernel_network(
    interfaces: frozenset[str], ipv4_routes: str, ipv6_routes: str, resolv_conf: str
) -> KernelNetwork:
    lines = ipv4_routes.splitlines()
    if not lines:
        raise ValueError("Actual kernel route inventory required")
    nameservers = tuple(
        tuple(parts[1:])
        for line in resolv_conf.splitlines()
        if (parts := line.split())[:1] == ["nameserver"]
    )
    return KernelNetwork(
        interfaces,
        tuple(ipv4_route(line) for line in lines[1:]),
        tuple(ipv6_interface(line) for line in ipv6_routes.splitlines()),
        nameservers,
    )


class LinuxNetworkInventory:
    def current(self) -> KernelNetwork:
        return kernel_network(
            frozenset(entry.name for entry in Path("/sys/class/net").iterdir()),
            Path("/proc/net/route").read_text(encoding="ascii"),
            Path("/proc/net/ipv6_route").read_text(encoding="ascii"),
            Path("/etc/resolv.conf").read_text(encoding="ascii"),
        )
