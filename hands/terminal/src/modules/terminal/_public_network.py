"""Routing boundary adapters; routing facts never replace controller authority."""

from terminal_hand.application.public_network import VerifyPublicNetwork
from terminal_hand.domain.public_network import PublicRouting
from terminal_hand.infrastructure.network_inventory import LinuxNetworkInventory, kernel_network

from node_protocol.json_boundary import decode_json
from node_protocol.network_attestation import PublicRoutingFacts


def decode_facts(encoded: str) -> PublicRouting:
    if not 0 < len(encoded) <= 1024:
        raise ValueError("Bounded routing facts required")
    value = decode_json(encoded, PublicRoutingFacts)
    return PublicRouting(value.subnet, value.gateway, tuple(value.dns))


def encode_facts(value: PublicRouting) -> str:
    return PublicRoutingFacts(
        subnet=value.subnet, gateway=value.gateway, dns=["127.0.0.11"]
    ).model_dump_json()


def validate_kernel(
    value: PublicRouting, interfaces: set[str], ipv4_routes: str, ipv6_routes: str, resolv_conf: str
) -> None:
    inventory = kernel_network(frozenset(interfaces), ipv4_routes, ipv6_routes, resolv_conf)
    inventory.require(value)


def require_kernel(value: PublicRouting) -> None:
    VerifyPublicNetwork(LinuxNetworkInventory()).execute(value)
