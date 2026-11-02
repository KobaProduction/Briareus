"""Root-only controller policy attestation for an explicit public Node profile."""

import os
import stat
from pathlib import Path
from typing import Protocol
from uuid import UUID

from modules.terminal._public_network import require_kernel

from node_protocol import Deployment
from node_protocol.json_boundary import decode_json
from node_protocol.network_attestation import PublicNetworkAttestation
from terminal_hand.domain.public_network import PublicRouting, require_public_supervisor


class RoutingPlacement(Protocol):
    @property
    def node_uuid(self) -> UUID: ...

    @property
    def project_uuid(self) -> UUID: ...

    @property
    def id(self) -> UUID: ...

    @property
    def fingerprint(self) -> str: ...


def validate_attestation(value: PublicNetworkAttestation, spec: RoutingPlacement) -> PublicRouting:
    value.require_placement(spec.node_uuid, spec.project_uuid, spec.id, spec.fingerprint)
    return PublicRouting(value.subnet, value.gateway, tuple(value.dns))


def read_attestation(
    spec: Deployment, path: Path = Path("/terminal-link/network-policy.json")
) -> PublicRouting | None:
    network = spec.configuration.network if spec.configuration is not None else None
    if network is None:
        return None
    require_public_supervisor(spec.release.module, network.profile, os.geteuid())
    parent = os.lstat(path.parent)
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != 0
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ValueError("Private controller policy directory required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        source = os.fstat(descriptor)
        if (
            not stat.S_ISREG(source.st_mode)
            or source.st_uid != 0
            or source.st_nlink != 1
            or stat.S_IMODE(source.st_mode) != 0o600
            or not 0 < source.st_size <= 4096
        ):
            raise ValueError("Private bounded controller policy file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            encoded = stream.read(4097)
        if len(encoded) > 4096:
            raise ValueError("Bounded controller policy file required")
        value = validate_attestation(decode_json(encoded, PublicNetworkAttestation), spec)
    finally:
        os.close(descriptor)
    mapping = [
        tuple(map(int, line.split()))
        for line in Path("/proc/self/uid_map").read_text().splitlines()
    ]
    if not mapping or mapping[0][0] != 0 or mapping[0][1] == 0:
        raise ValueError("Dedicated rootless public Terminal supervisor required")
    require_kernel(value)
    return value
