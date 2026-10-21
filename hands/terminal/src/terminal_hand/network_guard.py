"""Root-only controller policy attestation for an explicit public Node profile."""
import os
import re
import stat
from pathlib import Path

from node_protocol.files import strict_json
from modules.terminal._public_network import facts, require_kernel

KEYS = frozenset({"profile", "node_uuid", "project_uuid", "placement_uuid", "fingerprint",
                  "bridge", "subnet", "gateway", "dns", "policy_sha256", "ready"})


def validate_attestation(value, spec):
    if (not isinstance(value, dict) or set(value) != KEYS or value.get("profile") != "public"
        or value.get("ready") is not True or value.get("node_uuid") != str(spec.node_uuid)
        or value.get("project_uuid") != str(spec.project_uuid) or value.get("placement_uuid") != str(spec.id)
        or value.get("fingerprint") != spec.fingerprint
        or not isinstance(value.get("bridge"), str) or re.fullmatch(r"br-[0-9a-f]{12}", value["bridge"]) is None
        or not isinstance(value.get("policy_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", value["policy_sha256"]) is None):
        raise ValueError("Current controller-applied public network policy attestation required")
    return facts({key: value[key] for key in ("subnet", "gateway", "dns")})


def read_attestation(spec, path=Path("/terminal-link/network-policy.json")):
    network = spec.configuration.network if spec.configuration is not None else None
    if network is None:
        return None
    if spec.release.module != "terminal" or network.profile != "public" or os.geteuid() != 0:
        raise ValueError("Trusted Node Terminal public profile required")
    parent = os.lstat(path.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError("Private controller policy directory required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        source = os.fstat(descriptor)
        if (not stat.S_ISREG(source.st_mode) or source.st_uid != 0 or source.st_nlink != 1
            or stat.S_IMODE(source.st_mode) != 0o600 or not 0 < source.st_size <= 4096):
            raise ValueError("Private bounded controller policy file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            encoded = stream.read(4097)
        if len(encoded) > 4096:
            raise ValueError("Bounded controller policy file required")
        value = validate_attestation(strict_json(encoded), spec)
    finally:
        os.close(descriptor)
    mapping = [tuple(map(int, line.split())) for line in Path("/proc/self/uid_map").read_text().splitlines()]
    if not mapping or mapping[0][0] != 0 or mapping[0][1] == 0:
        raise ValueError("Dedicated rootless public Terminal supervisor required")
    require_kernel(value)
    return value
