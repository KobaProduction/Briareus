"""Pure fixed bridge policy and deterministic owner-scoped netfilter rules."""

import hashlib
import ipaddress
import json
import re
import shlex
from dataclasses import asdict, dataclass
from uuid import UUID

DOCKER_VERSION = "28.3.2"
BRIDGE = re.compile(r"br-[a-f0-9]{12}\Z", re.ASCII)
PRIVATE_V4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "168.63.129.16/32",
)


@dataclass(frozen=True, slots=True)
class PolicyDescription:
    node_uuid: str
    placement_uuid: str
    bridge: str
    ipv4_subnet: str
    control_addresses: tuple[str, ...]
    docker_version: str


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

    def __post_init__(self) -> None:
        for value in (self.node_uuid, self.placement_uuid):
            parsed = UUID(value)
            if parsed.version != 4 or str(parsed) != value:
                raise PolicyUnavailable("Canonical owner identities required")
        if self.docker_version != DOCKER_VERSION or not BRIDGE.fullmatch(self.bridge):
            raise PolicyUnavailable("Approved rootless Docker version and derived bridge required")
        subnet = ipaddress.ip_network(self.ipv4_subnet, strict=True)
        if subnet.version != 4 or not subnet.is_private or not 16 <= subnet.prefixlen <= 30:
            raise PolicyUnavailable("Explicit bounded private worker IPv4 subnet required")
        controls: object = self.control_addresses
        if (
            not isinstance(controls, tuple)
            or not 1 <= len(self.control_addresses) <= 128
            or len(set(self.control_addresses)) != len(self.control_addresses)
        ):
            raise PolicyUnavailable("Explicit bounded Node/Core address deny set required")
        for value in self.control_addresses:
            address = ipaddress.ip_address(value)
            if str(address) != value or "%" in value:
                raise PolicyUnavailable("Canonical control IP address required")

    def wire(self) -> PolicyDescription:
        return PolicyDescription(
            self.node_uuid,
            self.placement_uuid,
            self.bridge,
            self.ipv4_subnet,
            tuple(sorted(self.control_addresses)),
            self.docker_version,
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self.wire()), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def owner(self) -> str:
        return hashlib.sha256(
            (self.node_uuid + ":" + self.placement_uuid + ":" + self.bridge).encode()
        ).hexdigest()[:20]

    def chain(self, family: int, kind: str) -> str:
        return "BRI" + str(family) + kind + "_" + self.owner

    def rules(self, family: int) -> list[tuple[str, ...]]:
        forward, inbound = self.chain(family, "F"), self.chain(family, "I")
        result: list[tuple[str, ...]] = []
        if family == 4:
            networks = list(PRIVATE_V4) + [
                value + "/32"
                for value in self.control_addresses
                if ipaddress.ip_address(value).version == 4
            ]
            result.extend(
                ("-A", forward, "-d", value, "-j", "DROP") for value in dict.fromkeys(networks)
            )
            result += [
                ("-A", forward, "-m", "conntrack", "--ctstate", "INVALID", "-j", "DROP"),
                ("-A", forward, "-p", "tcp", "-j", "RETURN"),
                ("-A", forward, "-p", "udp", "-j", "RETURN"),
            ]
        result += [("-A", forward, "-j", "DROP"), ("-A", inbound, "-j", "DROP")]
        return result

    def restore_script(self, family: int) -> str:
        forward, inbound = self.chain(family, "F"), self.chain(family, "I")
        lines = [
            "*filter",
            ":" + forward + " - [0:0]",
            ":" + inbound + " - [0:0]",
            "-F " + forward,
            "-F " + inbound,
        ]
        lines += [shlex.join(rule) for rule in self.rules(family)]
        return "\n".join([*lines, "COMMIT", ""])

    def hooks(self, family: int) -> list[tuple[str, ...]]:
        forward_anchor = "DOCKER-USER" if family == 4 else "FORWARD"
        marker = "briareus:" + self.owner
        return [
            (
                "-A",
                forward_anchor,
                "-i",
                self.bridge,
                "-m",
                "comment",
                "--comment",
                marker,
                "-j",
                self.chain(family, "F"),
            ),
            (
                "-A",
                "INPUT",
                "-i",
                self.bridge,
                "-m",
                "comment",
                "--comment",
                marker,
                "-j",
                self.chain(family, "I"),
            ),
        ]
