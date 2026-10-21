"""Routing facts for an already firewalled public Terminal placement.

These public facts are NOT permission or proof of a firewall. The trusted
parent validates its root-only controller attestation before launching this
UID. Network policy is applied/read back in the dedicated rootless daemon
namespace, while the worker itself never gets NET_ADMIN or an engine socket.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path


def facts(value):
    if not isinstance(value, dict) or set(value) != {"subnet", "gateway", "dns"}:
        raise ValueError("Exact public routing facts required")
    if not isinstance(value["subnet"], str) or not isinstance(value["gateway"], str):
        raise ValueError("Canonical IPv4 routing facts required")
    network = ipaddress.IPv4Network(value["subnet"], strict=True)
    private = [ipaddress.IPv4Network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    gateway = ipaddress.IPv4Address(value["gateway"])
    if (str(network) != value["subnet"] or str(gateway) != value["gateway"]
        or not 16 <= network.prefixlen <= 30 or not any(network.subnet_of(parent) for parent in private)
        or gateway not in network or gateway in {network.network_address, network.broadcast_address}
        or value["dns"] != ["127.0.0.11"]):
        raise ValueError("Approved private bridge and embedded DNS facts required")
    return {"subnet": str(network), "gateway": str(gateway), "dns": ["127.0.0.11"]}


def decode_facts(encoded):
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 1024:
        raise ValueError("Bounded routing facts required")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate routing fact")
            result[key] = value
        return result
    return facts(json.loads(encoded, object_pairs_hook=unique))


def validate_kernel(value, interfaces, ipv4_routes, ipv6_routes, resolv_conf):
    value = facts(value)
    if interfaces != {"lo", "eth0"}:
        raise ValueError("One private worker bridge interface required")
    network = ipaddress.IPv4Network(value["subnet"])
    gateway = ipaddress.IPv4Address(value["gateway"])
    seen = set()
    lines = ipv4_routes.splitlines()
    if not lines:
        raise ValueError("Actual kernel route inventory required")
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 11:
            raise ValueError("Unexpected kernel route format")
        destination, route_gateway, mask = (ipaddress.IPv4Address(int(parts[index], 16).to_bytes(4, "little"))
                                             for index in (1, 2, 7))
        flags = int(parts[3], 16)
        if parts[0] == "lo" and destination.is_loopback and int(route_gateway) == 0:
            continue
        if parts[0] != "eth0":
            raise ValueError("Unexpected network route interface")
        if int(destination) == 0 and int(mask) == 0 and route_gateway == gateway and flags == 3:
            kind = "default"
        elif destination == network.network_address and str(mask) == str(network.netmask) and int(route_gateway) == 0 and flags == 1:
            kind = "connected"
        else:
            raise ValueError("Kernel routes do not match the controller's placement facts")
        if kind in seen:
            raise ValueError("Duplicate public network route")
        seen.add(kind)
    if seen != {"default", "connected"}:
        raise ValueError("Exact connected prefix and default gateway required")
    # The first public profile is IPv4-only; the trusted helper also denies
    # IPv6. A new IPv6 interface must not silently bypass this contract.
    for line in ipv6_routes.splitlines():
        parts = line.split()
        if len(parts) < 10 or parts[-1] != "lo":
            raise ValueError("Unexpected non-loopback IPv6 route")
    nameservers = [line.split()[1:] for line in resolv_conf.splitlines() if line.split()[:1] == ["nameserver"]]
    if nameservers != [["127.0.0.11"]]:
        raise ValueError("Controller-selected Docker embedded DNS required")


def require_kernel(value):
    validate_kernel(value, {entry.name for entry in Path("/sys/class/net").iterdir()},
        Path("/proc/net/route").read_text(encoding="ascii"),
        Path("/proc/net/ipv6_route").read_text(encoding="ascii"),
        Path("/etc/resolv.conf").read_text(encoding="ascii"))
