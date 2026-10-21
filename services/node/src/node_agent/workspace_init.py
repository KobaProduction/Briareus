"""One-shot rootless workspace and private executor directory initialization."""
import ctypes
import errno
import ipaddress
import json
import os
import re
import stat
from uuid import UUID

MARKER = ".briareus-workspace.json"


def expected_identity(environ):
    result = {"kind": "briareus.workspace"}
    for name in ("node", "project", "workspace"):
        value = environ["BRIAREUS_" + name.upper() + "_UUID"]
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("Canonical workspace UUID required")
        result[name + "_uuid"] = value
    return result


def initialize(root, identity):
    # Only the data subdirectory is exposed to workers. Rootless uid 0 owns
    # the outer metadata directory; worker uid 1000 cannot alter its marker.
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if (info.st_uid, info.st_gid) != (0, 0):
            raise ValueError("Workspace volume metadata must belong to its initializer")
        if os.listdir(directory):
            marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                metadata = os.fstat(marker)
                data = os.stat("data", dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (0, 0, 0o600)
                    or metadata.st_size > 4096 or stat.S_IMODE(info.st_mode) != 0o700
                    or not stat.S_ISDIR(data.st_mode)
                    or (data.st_uid, data.st_gid, stat.S_IMODE(data.st_mode)) != (1000, 1000, 0o700)
                    or json.loads(os.read(marker, 4097)) != identity):
                    raise ValueError("Existing workspace identity or ownership mismatch")
            finally:
                os.close(marker)
            return
        marker = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            with os.fdopen(marker, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(marker)
        finally:
            os.close(marker)
        os.mkdir("data", mode=0o700, dir_fd=directory)
        data = os.open("data", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            os.fchmod(data, 0o700)
            os.fchown(data, 1000, 1000)
            os.fsync(data)
        finally:
            os.close(data)
        os.fchmod(directory, 0o700)
        os.fsync(directory)
    finally:
        os.close(directory)


def main():
    if os.geteuid() != 0:
        raise ValueError("Dedicated rootless initializer uid required")
    initialize("/workspace", expected_identity(os.environ))
    if "BRIAREUS_RUNTIME_WORKER" in os.environ:
        identity = expected_identity(os.environ)
        raw = os.environ.get("BRIAREUS_NETWORK_POLICY_ATTESTATION")
        attestation = None
        if raw is not None:
            if len(raw.encode()) > 4096:
                raise ValueError("Bounded network attestation required")
            attestation = json.loads(raw)
            validate_attestation(attestation, identity, os.environ["BRIAREUS_RUNTIME_WORKER"])
        initialize_runtime("/node-link", os.environ["BRIAREUS_RUNTIME_WORKER"], attestation)



def validate_attestation(value, identity, runtime_worker):
    from node_protocol.naming import worker_name
    keys = {"profile", "node_uuid", "project_uuid", "placement_uuid", "fingerprint", "bridge", "subnet", "gateway", "dns", "policy_sha256", "ready"}
    if not isinstance(value, dict) or set(value) != keys or value["profile"] != "public" or value["ready"] is not True:
        raise ValueError("Exact ready public-network attestation required")
    for key in ("node_uuid", "project_uuid", "placement_uuid"):
        parsed = UUID(value[key])
        if parsed.version != 4 or str(parsed) != value[key]:
            raise ValueError("Canonical network identity required")
    if any(value[key] != identity[key] for key in ("node_uuid", "project_uuid")):
        raise ValueError("Network identity does not match workspace")
    if any(not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key], re.ASCII)
           for key in ("fingerprint", "policy_sha256")):
        raise ValueError("Network fingerprints required")
    if worker_name(value["node_uuid"], value["placement_uuid"], value["fingerprint"]) != runtime_worker:
        raise ValueError("Network identity does not match executor")
    if not re.fullmatch(r"br-[a-f0-9]{12}", value["bridge"], re.ASCII) or value["dns"] != ["127.0.0.11"]:
        raise ValueError("Private Docker bridge required")
    subnet = ipaddress.ip_network(value["subnet"], strict=True)
    gateway = ipaddress.ip_address(value["gateway"])
    if (subnet.version != 4 or not subnet.is_private or str(subnet) != value["subnet"]
        or gateway.version != 4 or str(gateway) != value["gateway"] or gateway not in subnet
        or gateway in {subnet.network_address, subnet.broadcast_address}):
        raise ValueError("Canonical private IPv4 network required")
    return value


def write_attestation(directory, value):
    """Publish once atomically; an existing proof must have exact bytes and ownership."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 4096:
        raise ValueError("Bounded network attestation required")
    name = "network-policy.json"
    try:
        existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        temporary = ".network-policy-" + os.urandom(12).hex()
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
            os.fsync(descriptor)
            rename = ctypes.CDLL(None, use_errno=True).renameat2
            if rename(directory, temporary.encode(), directory, name.encode(), 1) != 0:
                code = ctypes.get_errno()
                if code != errno.EEXIST:
                    raise OSError(code, os.strerror(code))
            os.fsync(directory)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
        existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(existing)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o600)
            or info.st_size != len(raw) or os.read(existing, 4097) != raw):
            raise ValueError("Existing network attestation differs from accepted placement")
    finally:
        os.close(existing)


def initialize_runtime(root, name, attestation=None):
    if not re.fullmatch(r"briareus-[a-f0-9]{48}", name, flags=re.ASCII):
        raise ValueError("Derived executor identity required")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in ("workers", name):
            info = os.fstat(directory)
            if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o700):
                raise ValueError("Private rootless runtime directory required")
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory)
                os.fsync(directory)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        info = os.fstat(directory)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o700):
            raise ValueError("Foreign executor runtime directory")
        if attestation is not None:
            write_attestation(directory, attestation)
    finally:
        os.close(directory)


if __name__ == "__main__":
    main()
