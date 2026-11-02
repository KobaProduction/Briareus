"""Native kernel observations and fixed commands for the owned execution bridge."""

from __future__ import annotations

import ipaddress
import os
import shlex
import socket
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator

from node_agent.domain.network_policy import NetworkPolicy, PolicyUnavailable
from node_agent.domain.policy_readback import BridgeSnapshot, require_bridge


class NamespaceFacts(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    netns_inode: int
    rootless_owner_uid: int
    capabilities: Literal["NET_ADMIN"] = "NET_ADMIN"


def namespace_facts() -> NamespaceFacts:
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    mappings = [
        tuple(map(int, line.split()))
        for line in Path("/proc/self/uid_map").read_text().splitlines()
    ]
    if (
        os.geteuid() != 0
        or not mappings
        or mappings[0][0] != 0
        or mappings[0][1] == 0
        or fields["NoNewPrivs"].strip() != "1"
        or int(fields["CapEff"].strip(), 16) != 1 << 12
    ):
        raise PolicyUnavailable("Dedicated rootless NET_ADMIN-only helper required")
    return NamespaceFacts(
        netns_inode=os.stat("/proc/self/ns/net").st_ino, rootless_owner_uid=mappings[0][1]
    )


def _run(arguments: list[str], *, stdin_text: str | None = None) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed owner-scoped ip/netfilter argv; no shell
        arguments,
        input=stdin_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "XTABLES_LOCKFILE": "/tmp/briareus-netfilter.lock",  # noqa: S108 -- private helper tmpfs
        },
    )
    if result.returncode != 0 or len(result.stdout) > 2 * 1024 * 1024:
        raise PolicyUnavailable("Scoped network policy command failed")
    return result.stdout


def _saved_rules(family: int) -> tuple[set[str], list[tuple[str, ...]]]:
    binary = "iptables-save" if family == 4 else "ip6tables-save"
    text = _run([binary, "-t", "filter"])
    chains = {line[1:].split(" ", 1)[0] for line in text.splitlines() if line.startswith(":")}
    rules = [tuple(shlex.split(line)) for line in text.splitlines() if line.startswith("-A ")]
    return chains, rules


class _LinkInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    info_kind: str | None = None


class _LinkObservation(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    linkinfo: _LinkInfo | None = None


class _InetAddress(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    family: Literal["inet"]
    local: str
    prefixlen: int | str


class _OtherAddress(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    family: Annotated[str, BeforeValidator(str)] = ""

    @field_validator("family")
    @classmethod
    def non_inet(cls, value: str) -> str:
        if value == "inet":
            raise ValueError("IPv4 address observations require local and prefix fields")
        return value


class _InterfaceAddresses(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    addr_info: list[_InetAddress | _OtherAddress] = Field(default_factory=list)


def _verify_bridge(policy: NetworkPolicy) -> None:
    if policy.bridge not in {name for _, name in socket.if_nameindex()}:
        raise PolicyUnavailable("Owned bridge is unavailable")
    links = TypeAdapter(list[_LinkObservation]).validate_json(
        _run(["ip", "-d", "-j", "link", "show", "dev", policy.bridge])
    )
    addresses = TypeAdapter(list[_InterfaceAddresses]).validate_json(
        _run(["ip", "-j", "-4", "addr", "show", "dev", policy.bridge])
    )
    subnets = frozenset(
        str(ipaddress.ip_network(item.local + "/" + str(item.prefixlen), strict=False))
        for address in addresses
        for item in address.addr_info
        if isinstance(item, _InetAddress)
    )
    require_bridge(
        policy,
        BridgeSnapshot(
            tuple(link.linkinfo.info_kind if link.linkinfo is not None else None for link in links),
            subnets,
        ),
    )
