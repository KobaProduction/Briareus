"""Direct public egress in the dedicated Docker 28.3.2 rootless daemon netns.

Only the fixed, one-shot helper gets NET_ADMIN. A worker gets no capabilities,
host networking or engine socket. The controller must create an EMPTY bridge,
apply/read back this policy, and only then create/start its worker. No global
host firewall, default table policy, Docker rule or unrelated bridge is flushed.

Docker 29.5 changed rootless host-network semantics. Other engine versions are
deliberately rejected until their namespace/packet path is separately accepted.
IPv6 is blocked for this MVP; IPv4 TCP/UDP (including DNS) goes directly out.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict

from node_protocol.json_boundary import decode_json

from .application.network_policy import ManageNetworkPolicy
from .domain.network_policy import (
    BRIDGE,
    DOCKER_VERSION,
    PRIVATE_V4,
    NetworkPolicy,
    PolicyUnavailable,
)
from .infrastructure.container_models import ContainerConfiguration, ContainerHost, LogConfiguration
from .infrastructure.kernel_readback import NamespaceFacts as NamespaceFacts
from .infrastructure.kernel_readback import _run as _run
from .infrastructure.kernel_readback import _saved_rules as _saved_rules
from .infrastructure.kernel_readback import _verify_bridge as _verify_bridge
from .infrastructure.kernel_readback import namespace_facts as namespace_facts

__all__ = [
    "BRIDGE",
    "DOCKER_VERSION",
    "PRIVATE_V4",
    "NetworkPolicy",
    "PolicyUnavailable",
    "apply",
    "helper_config",
    "helper_name",
    "parse_policy",
    "readback",
    "remove",
]


class PolicyReadback(NamespaceFacts):
    state: Literal["ready"] = "ready"
    fingerprint: str
    bridge: str
    ipv4: Literal["direct_public_tcp_udp"] = "direct_public_tcp_udp"
    ipv6: Literal["denied"] = "denied"


class PolicyRemoval(NamespaceFacts):
    state: Literal["removed"] = "removed"
    fingerprint: str
    bridge: str


class PolicyInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    node_uuid: str
    placement_uuid: str
    bridge: str
    ipv4_subnet: str
    control_addresses: list[str]
    docker_version: str

    @classmethod
    def from_domain(cls, policy: NetworkPolicy) -> PolicyInput:
        description = policy.wire()
        return cls(
            node_uuid=description.node_uuid,
            placement_uuid=description.placement_uuid,
            bridge=description.bridge,
            ipv4_subnet=description.ipv4_subnet,
            control_addresses=list(description.control_addresses),
            docker_version=description.docker_version,
        )


type PolicyAction = Literal["apply", "readback", "remove"]


class PolicyCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    action: PolicyAction
    policy: PolicyInput


def parse_policy(row: PolicyInput) -> NetworkPolicy:
    return NetworkPolicy(
        row.node_uuid,
        row.placement_uuid,
        row.bridge,
        row.ipv4_subnet,
        tuple(row.control_addresses),
        row.docker_version,
    )


def _verify_saved(
    policy: NetworkPolicy, family: int, chains: set[str], rules: list[tuple[str, ...]]
) -> None:
    from .domain.policy_readback import PolicySnapshot, require_saved

    require_saved(policy, family, PolicySnapshot(frozenset(chains), tuple(rules)))


def policy_manager() -> ManageNetworkPolicy:
    from .infrastructure.kernel_policy import KernelNetworkPolicy

    return ManageNetworkPolicy(KernelNetworkPolicy())


def readback(policy: NetworkPolicy) -> PolicyReadback:
    facts = policy_manager().readback(policy)
    return PolicyReadback(
        fingerprint=policy.fingerprint,
        bridge=policy.bridge,
        netns_inode=facts.netns_inode,
        rootless_owner_uid=facts.rootless_owner_uid,
    )


def apply(policy: NetworkPolicy) -> PolicyReadback:
    facts = policy_manager().apply(policy)
    return PolicyReadback(
        fingerprint=policy.fingerprint,
        bridge=policy.bridge,
        netns_inode=facts.netns_inode,
        rootless_owner_uid=facts.rootless_owner_uid,
    )


def remove(policy: NetworkPolicy) -> PolicyRemoval:
    facts = policy_manager().remove(policy)
    return PolicyRemoval(
        fingerprint=policy.fingerprint,
        bridge=policy.bridge,
        netns_inode=facts.netns_inode,
        rootless_owner_uid=facts.rootless_owner_uid,
    )


def helper_name(policy: NetworkPolicy, operation: PolicyAction = "apply") -> str:
    if operation not in {"apply", "readback", "remove"}:
        raise PolicyUnavailable("Fixed helper operation required")
    return "briareus-network-" + policy.owner + "-" + operation


def helper_config(
    policy: NetworkPolicy, image: str, operation: PolicyAction = "apply"
) -> ContainerConfiguration:
    """Only the one-shot helper enters the dedicated daemon's host netns."""
    helper_name(policy, operation)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}", image):
        raise PolicyUnavailable("Immutable approved network helper image required")
    request = PolicyCommand(
        action=operation, policy=PolicyInput.from_domain(policy)
    ).model_dump_json()
    return ContainerConfiguration(
        image=image,
        user="0:0",
        command=["/app/.venv/bin/python", "-m", "node_agent.network_policy"],
        environment=["BRIAREUS_NETWORK_POLICY_REQUEST=" + request],
        labels={
            "io.briareus.node": policy.node_uuid,
            "io.briareus.deployment": policy.placement_uuid,
            "io.briareus.role": "network-policy-helper",
            "io.briareus.network-policy": policy.fingerprint,
            "io.briareus.network-operation": operation,
        },
        host=ContainerHost(
            network_mode="host",
            cap_add=["NET_ADMIN"],
            memory=64 * 1024**2,
            memory_swap=64 * 1024**2,
            nano_cpus=100_000_000,
            pids=32,
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=1m,uid=0,gid=0,mode=0700"},  # noqa: S108 -- private helper tmpfs mount target
            log=LogConfiguration(options={"max-size": "1m", "max-file": "1"}),
        ),
    )


def main() -> None:
    configured = os.environ.get("BRIAREUS_NETWORK_POLICY_REQUEST")
    raw = configured.encode() if configured is not None else sys.stdin.buffer.read(65_537)
    if not raw or len(raw) > 65_536:
        raise PolicyUnavailable("Bounded helper input required")
    command = decode_json(raw, PolicyCommand)
    policy = parse_policy(command.policy)
    operation = {"apply": apply, "readback": readback, "remove": remove}[command.action]
    print(json.dumps(operation(policy).model_dump(), separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
