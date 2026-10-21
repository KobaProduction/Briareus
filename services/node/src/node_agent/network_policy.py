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

import hashlib
import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

DOCKER_VERSION = "28.3.2"
BRIDGE = re.compile(r"br-[a-f0-9]{12}\Z", re.ASCII)
PRIVATE_V4 = ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
              "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
              "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
              "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "168.63.129.16/32")


class PolicyUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class NetworkPolicy:
    node_uuid: str
    placement_uuid: str
    bridge: str
    ipv4_subnet: str
    control_addresses: tuple[str, ...]
    docker_version: str = DOCKER_VERSION

    def __post_init__(self):
        for value in (self.node_uuid, self.placement_uuid):
            parsed = UUID(value)
            if parsed.version != 4 or str(parsed) != value:
                raise PolicyUnavailable("Canonical owner identities required")
        if self.docker_version != DOCKER_VERSION or not BRIDGE.fullmatch(self.bridge):
            raise PolicyUnavailable("Approved rootless Docker version and derived bridge required")
        subnet = ipaddress.ip_network(self.ipv4_subnet, strict=True)
        if subnet.version != 4 or not subnet.is_private or not 16 <= subnet.prefixlen <= 30:
            raise PolicyUnavailable("Explicit bounded private worker IPv4 subnet required")
        if (not isinstance(self.control_addresses, tuple) or not 1 <= len(self.control_addresses) <= 128
            or len(set(self.control_addresses)) != len(self.control_addresses)):
            raise PolicyUnavailable("Explicit bounded Node/Core address deny set required")
        for value in self.control_addresses:
            parsed = ipaddress.ip_address(value)
            if str(parsed) != value or "%" in value:
                raise PolicyUnavailable("Canonical control IP address required")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"node_uuid", "placement_uuid", "bridge", "ipv4_subnet", "control_addresses", "docker_version"}:
            raise PolicyUnavailable("Exact network policy object required")
        if not isinstance(value["control_addresses"], list):
            raise PolicyUnavailable("Control address list required")
        return cls(**{**value, "control_addresses": tuple(value["control_addresses"])})

    def wire(self):
        return {"node_uuid": self.node_uuid, "placement_uuid": self.placement_uuid,
                "bridge": self.bridge, "ipv4_subnet": self.ipv4_subnet, "control_addresses": sorted(self.control_addresses),
                "docker_version": self.docker_version}

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.wire(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def owner(self):
        return hashlib.sha256((self.node_uuid + ":" + self.placement_uuid + ":" + self.bridge).encode()).hexdigest()[:20]

    def chain(self, family, kind):
        return "BRI" + str(family) + kind + "_" + self.owner

    def rules(self, family):
        forward, inbound = self.chain(family, "F"), self.chain(family, "I")
        result = []
        if family == 4:
            networks = list(PRIVATE_V4) + [value + "/32" for value in self.control_addresses
                                           if ipaddress.ip_address(value).version == 4]
            for value in dict.fromkeys(networks):
                result.append(("-A", forward, "-d", value, "-j", "DROP"))
            result += [("-A", forward, "-m", "conntrack", "--ctstate", "INVALID", "-j", "DROP"),
                       ("-A", forward, "-p", "tcp", "-j", "RETURN"),
                       ("-A", forward, "-p", "udp", "-j", "RETURN")]
        result += [("-A", forward, "-j", "DROP"), ("-A", inbound, "-j", "DROP")]
        return result

    def restore_script(self, family):
        forward, inbound = self.chain(family, "F"), self.chain(family, "I")
        lines = ["*filter", ":" + forward + " - [0:0]", ":" + inbound + " - [0:0]",
                 "-F " + forward, "-F " + inbound]
        lines += [shlex.join(rule) for rule in self.rules(family)]
        return "\n".join([*lines, "COMMIT", ""])

    def hooks(self, family):
        forward_anchor = "DOCKER-USER" if family == 4 else "FORWARD"
        marker = "briareus:" + self.owner
        return [("-A", forward_anchor, "-i", self.bridge, "-m", "comment", "--comment", marker,
                 "-j", self.chain(family, "F")),
                ("-A", "INPUT", "-i", self.bridge, "-m", "comment", "--comment", marker,
                 "-j", self.chain(family, "I"))]


def namespace_facts():
    fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    mappings = [tuple(map(int, line.split())) for line in Path("/proc/self/uid_map").read_text().splitlines()]
    if (os.geteuid() != 0 or not mappings or mappings[0][0] != 0 or mappings[0][1] == 0
        or fields["NoNewPrivs"].strip() != "1" or int(fields["CapEff"].strip(), 16) != 1 << 12):
        raise PolicyUnavailable("Dedicated rootless NET_ADMIN-only helper required")
    return {"netns_inode": os.stat("/proc/self/ns/net").st_ino,
            "rootless_owner_uid": mappings[0][1], "capabilities": "NET_ADMIN"}


def _run(arguments, *, input=None):
    result = subprocess.run(arguments, input=input, capture_output=True, text=True, timeout=10,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C",
             "XTABLES_LOCKFILE": "/tmp/briareus-netfilter.lock"})
    if result.returncode != 0 or len(result.stdout) > 2 * 1024 * 1024:
        raise PolicyUnavailable("Scoped network policy command failed")
    return result.stdout


def _saved_rules(family):
    binary = "iptables-save" if family == 4 else "ip6tables-save"
    text = _run([binary, "-t", "filter"])
    chains = {line[1:].split(" ", 1)[0] for line in text.splitlines() if line.startswith(":")}
    rules = [tuple(shlex.split(line)) for line in text.splitlines() if line.startswith("-A ")]
    return chains, rules


def _verify_saved(policy, family, chains, rules):
    if family == 4:
        forwarding = [rule for rule in rules if rule[1] == "FORWARD"]
        if not forwarding or forwarding[0] != ("-A", "FORWARD", "-j", "DOCKER-USER"):
            raise PolicyUnavailable("Docker's early forwarding anchor is unavailable")
    owned = {policy.chain(family, "F"), policy.chain(family, "I")}
    if not owned <= chains:
        raise PolicyUnavailable("Owned network chains are missing")
    actual = [rule for rule in rules if rule[1] in owned]
    if actual != policy.rules(family):
        raise PolicyUnavailable("Owned network rules differ from policy")
    for hook in policy.hooks(family):
        anchor_rules = [rule for rule in rules if rule[1] == hook[1]]
        if anchor_rules.count(hook) != 1:
            raise PolicyUnavailable("Unique scoped network hook required")
        for earlier in anchor_rules[:anchor_rules.index(hook)]:
            # Earlier hooks for other exact bridges cannot bypass ours.
            if "!" in earlier or "-i" not in earlier:
                raise PolicyUnavailable("An earlier broad rule can bypass network policy")
            interface = earlier[earlier.index("-i") + 1]
            if not BRIDGE.fullmatch(interface) or interface == policy.bridge:
                raise PolicyUnavailable("An earlier rule can bypass this bridge policy")


def _verify_bridge(policy):
    if policy.bridge not in {name for _, name in socket.if_nameindex()}:
        raise PolicyUnavailable("Owned bridge is unavailable")
    links = json.loads(_run(["ip", "-d", "-j", "link", "show", "dev", policy.bridge]))
    addresses = json.loads(_run(["ip", "-j", "-4", "addr", "show", "dev", policy.bridge]))
    subnets = {str(ipaddress.ip_network(item["local"] + "/" + str(item["prefixlen"]), strict=False))
               for address in addresses for item in address.get("addr_info", []) if item.get("family") == "inet"}
    if (len(links) != 1 or links[0].get("linkinfo", {}).get("info_kind") != "bridge"
        or subnets != {policy.ipv4_subnet}):
        raise PolicyUnavailable("Worker bridge type or IPv4 subnet differs from policy")


def readback(policy):
    facts = namespace_facts()
    _verify_bridge(policy)
    for family in (4, 6):
        _verify_saved(policy, family, *_saved_rules(family))
    return {"state": "ready", "fingerprint": policy.fingerprint, "bridge": policy.bridge,
            "ipv4": "direct_public_tcp_udp", "ipv6": "denied", **facts}


def apply(policy):
    namespace_facts()
    _verify_bridge(policy)
    # Existing bridge policies are replaced in a filter-table transaction;
    # only our two chains are flushed. Initial hook setup happens while the
    # controller still guarantees that no worker exists on this bridge.
    for family in (4, 6):
        binary = "iptables" if family == 4 else "ip6tables"
        restore = "iptables-restore" if family == 4 else "ip6tables-restore"
        chains, _ = _saved_rules(family)
        if family == 4 and "DOCKER-USER" not in chains:
            raise PolicyUnavailable("Docker iptables forwarding anchor is unavailable")
        _run([restore, "--wait", "3", "--noflush"], input=policy.restore_script(family))
        _, rules = _saved_rules(family)
        for hook in policy.hooks(family):
            if hook not in rules:
                _run([binary, "--wait", "3", "-I", hook[1], "1", *hook[2:]])
    return readback(policy)


def remove(policy):
    """Remove only exact derived bridge hooks/chains, including interrupted cleanup.

    Preflight both families before touching either. A mismatched rule or an
    unexpected reference refuses cleanup rather than flushing foreign policy.
    """
    facts = namespace_facts()
    _verify_bridge(policy)
    planned = []
    for family in (4, 6):
        chains, rules = _saved_rules(family)
        owned = {policy.chain(family, "F"), policy.chain(family, "I")}
        present = owned & chains
        actual = [rule for rule in rules if rule[1] in owned]
        expected = [rule for rule in policy.rules(family) if rule[1] in present]
        # An empty chain is valid after an interrupted cleanup flush.
        for chain in present:
            entries = [rule for rule in actual if rule[1] == chain]
            if entries and entries != [rule for rule in expected if rule[1] == chain]:
                raise PolicyUnavailable("Refusing to remove mismatched bridge policy")
        hooks = policy.hooks(family)
        references = [rule for rule in rules if "-j" in rule and rule[rule.index("-j") + 1] in owned]
        if any(rule not in hooks for rule in references) or any(references.count(hook) > 1 for hook in hooks):
            raise PolicyUnavailable("Refusing to remove foreign bridge policy references")
        planned.append((family, present, references))
    for family, present, references in planned:
        binary = "iptables" if family == 4 else "ip6tables"
        for rule in references:
            _run([binary, "--wait", "3", "-D", rule[1], *rule[2:]])
        for chain in sorted(present):
            _run([binary, "--wait", "3", "-F", chain])
        for chain in sorted(present):
            _run([binary, "--wait", "3", "-X", chain])
    for family in (4, 6):
        chains, rules = _saved_rules(family)
        owned = {policy.chain(family, "F"), policy.chain(family, "I")}
        if owned & chains or any("-j" in rule and rule[rule.index("-j") + 1] in owned for rule in rules):
            raise PolicyUnavailable("Bridge policy removal readback failed")
    return {"state": "removed", "fingerprint": policy.fingerprint, "bridge": policy.bridge, **facts}


def helper_name(policy, operation="apply"):
    if operation not in {"apply", "readback", "remove"}:
        raise PolicyUnavailable("Fixed helper operation required")
    return "briareus-network-" + policy.owner + "-" + operation


def helper_config(policy, image, operation="apply"):
    """One-shot Docker create body. The controller verifies owned network labels.

    The host network here belongs to the pinned rootless daemon, never to a
    worker. No host path, engine socket, secret or project volume is mounted.
    """
    helper_name(policy, operation)
    if not isinstance(image, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}", image):
        raise PolicyUnavailable("Immutable approved network helper image required")
    request = json.dumps({"action": operation, "policy": policy.wire()}, separators=(",", ":"))
    return {"Image": image, "User": "0:0", "Cmd": ["/app/.venv/bin/python", "-m", "node_agent.network_policy"],
        "Env": ["BRIAREUS_NETWORK_POLICY_REQUEST=" + request],
        "Labels": {"io.briareus.node": policy.node_uuid, "io.briareus.deployment": policy.placement_uuid,
            "io.briareus.role": "network-policy-helper", "io.briareus.network-policy": policy.fingerprint,
            "io.briareus.network-operation": operation},
        "HostConfig": {"NetworkMode": "host", "ReadonlyRootfs": True, "Privileged": False,
            "CapDrop": ["ALL"], "CapAdd": ["NET_ADMIN"], "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 64*1024**2, "MemorySwap": 64*1024**2, "NanoCpus": 100_000_000, "PidsLimit": 32,
            "RestartPolicy": {"Name": "no"}, "PublishAllPorts": False,
            "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=1m,uid=0,gid=0,mode=0700"},
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}}}}


def main():
    configured = os.environ.get("BRIAREUS_NETWORK_POLICY_REQUEST")
    raw = configured.encode() if configured is not None else sys.stdin.buffer.read(65_537)
    if not raw or len(raw) > 65_536:
        raise PolicyUnavailable("Bounded helper input required")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"action", "policy"}:
        raise PolicyUnavailable("Exact helper request required")
    policy = NetworkPolicy.from_dict(data["policy"])
    operation = {"apply": apply, "readback": readback, "remove": remove}.get(data["action"])
    if operation is None:
        raise PolicyUnavailable("Fixed network policy operation required")
    print(json.dumps(operation(policy), separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
