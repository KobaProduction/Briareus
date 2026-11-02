"""Stable project volume identity and strict managed helper ownership."""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    node_uuid: UUID
    project_uuid: UUID
    workspace_uuid: UUID

    @property
    def volume_name(self) -> str:
        return f"briareus-{self.node_uuid.hex}-{self.project_uuid.hex}-{self.workspace_uuid.hex}"


def helper_labels_match(actual: Mapping[str, str], expected: Mapping[str, str]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items()) and {
        key for key in actual if key.startswith("io.briareus.")
    } == set(expected)


def require_private_network(subnet_text: str, gateway_text: str) -> None:
    subnet = ipaddress.ip_network(subnet_text, strict=True)
    gateway = ipaddress.ip_address(gateway_text)
    if (
        subnet.version != 4
        or not subnet.is_private
        or str(subnet) != subnet_text
        or gateway.version != 4
        or str(gateway) != gateway_text
        or gateway not in subnet
        or gateway in {subnet.network_address, subnet.broadcast_address}
    ):
        raise ValueError("Canonical private IPv4 network required")
