"""Explicit small bridge ranges which cannot shadow configured control peers."""
import hashlib
import ipaddress

from .docker_engine import EngineFailure


def protected_addresses(engine):
    values = list(getattr(engine, "control_addresses", ()))
    for registry in getattr(engine, "allowed_registries", ()):
        host = registry.rsplit(":", 1)[0]
        try:
            values.append(str(ipaddress.ip_address(host)))
        except ValueError:
            # DNS registries need their resolved addresses in the explicitly
            # provisioned control set; never resolve an agent-controlled URL.
            pass
    if not values:
        raise EngineFailure("Execution network address conflict")
    return tuple(ipaddress.ip_address(value) for value in values)


def validate_network_addresses(engine, network):
    protected = protected_addresses(engine)
    for config in network.get("IPAM", {}).get("Config", []) or []:
        if config.get("Subnet"):
            subnet = ipaddress.ip_network(config["Subnet"], strict=True)
            if any(address.version == subnet.version and address in subnet for address in protected):
                raise EngineFailure("Execution network address conflict")


async def bridge_ipam(engine, name):
    rows = (await engine.request("GET", "/networks")).json()
    if not isinstance(rows, list) or len(rows) > 4096:
        raise EngineFailure("Execution network address conflict")
    occupied = []
    for row in rows:
        for config in row.get("IPAM", {}).get("Config", []) or []:
            if config.get("Subnet"):
                occupied.append(ipaddress.ip_network(config["Subnet"], strict=True))
    protected = protected_addresses(engine)
    # A /24 per bridge avoids consuming a /16 for every MCP placement. The
    # controller serializes placement changes; Docker rejects allocation races.
    start = int.from_bytes(hashlib.sha256(name.encode()).digest()[:2], "big") % 16384
    for offset in range(16384):
        index = (start + offset) % 16384
        subnet = ipaddress.ip_network(f"10.{64 + index // 256}.{index % 256}.0/24")
        if any(address.version == 4 and address in subnet for address in protected):
            continue
        if any(value.version == 4 and value.overlaps(subnet) for value in occupied):
            continue
        return {"Driver":"default", "Config":[{"Subnet":str(subnet), "Gateway":str(subnet.network_address + 1)}]}
    raise EngineFailure("Execution network address conflict")
