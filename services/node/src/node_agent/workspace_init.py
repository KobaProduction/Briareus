"""One-shot rootless filesystem adapter; never rewrites foreign workspace data."""

import ctypes
import errno
import json
import os
import re
import stat
from collections.abc import Mapping
from contextlib import suppress
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from node_protocol.json_boundary import decode_json
from node_protocol.naming import worker_name
from node_protocol.network_attestation import PublicNetworkAttestation

from .domain.workspace import require_private_network

MARKER = ".briareus-workspace.json"


class WorkspaceMarker(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["briareus.workspace"]
    node_uuid: str
    project_uuid: str
    workspace_uuid: str


def canonical_uuid(value: str) -> str:
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Canonical workspace UUID required")
    return value


def expected_identity(environ: Mapping[str, str]) -> WorkspaceMarker:
    return WorkspaceMarker(
        kind="briareus.workspace",
        node_uuid=canonical_uuid(environ["BRIAREUS_NODE_UUID"]),
        project_uuid=canonical_uuid(environ["BRIAREUS_PROJECT_UUID"]),
        workspace_uuid=canonical_uuid(environ["BRIAREUS_WORKSPACE_UUID"]),
    )


def verify_workspace(directory: int, info: os.stat_result, identity: WorkspaceMarker) -> None:
    marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        metadata = os.fstat(marker)
        data = os.stat("data", dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (0, 0, 0o600)
            or metadata.st_size > 4096
            or stat.S_IMODE(info.st_mode) != 0o700
            or not stat.S_ISDIR(data.st_mode)
            or (data.st_uid, data.st_gid, stat.S_IMODE(data.st_mode)) != (1000, 1000, 0o700)
            or WorkspaceMarker.model_validate_json(os.read(marker, 4097)) != identity
        ):
            raise ValueError("Existing workspace identity or ownership mismatch")
    finally:
        os.close(marker)


def create_workspace(directory: int, identity: WorkspaceMarker) -> None:
    marker = os.open(
        MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
    )
    try:
        raw = json.dumps(identity.model_dump(), sort_keys=True, separators=(",", ":")).encode()
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


def initialize(root: str, identity: WorkspaceMarker) -> None:
    # Root owns metadata; only its data subdirectory is exposed to the worker.
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if (info.st_uid, info.st_gid) != (0, 0):
            raise ValueError("Workspace volume metadata must belong to its initializer")
        if os.listdir(directory):
            verify_workspace(directory, info, identity)
        else:
            create_workspace(directory, identity)
    finally:
        os.close(directory)


def validate_attestation(
    proof: PublicNetworkAttestation, node_uuid: UUID, project_uuid: UUID, runtime_worker: str
) -> None:
    if proof.node_uuid != node_uuid or proof.project_uuid != project_uuid:
        raise ValueError("Network identity does not match workspace")
    if (
        worker_name(str(proof.node_uuid), str(proof.placement_uuid), proof.fingerprint)
        != runtime_worker
    ):
        raise ValueError("Network identity does not match executor")
    require_private_network(proof.subnet, proof.gateway)


def publish_attestation(directory: int, name: str, raw: bytes) -> None:
    temporary = ".network-policy-" + os.urandom(12).hex()
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
        os.fsync(descriptor)
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result: int = rename(directory, temporary.encode(), directory, name.encode(), 1)
        if result != 0:
            code = ctypes.get_errno()
            if code != errno.EEXIST:
                raise OSError(code, os.strerror(code))
        os.fsync(directory)
    finally:
        os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)


def write_attestation(directory: int, value: PublicNetworkAttestation) -> None:
    raw = value.canonical_bytes()
    if len(raw) > 4096:
        raise ValueError("Bounded network attestation required")
    name = "network-policy.json"
    try:
        existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        publish_attestation(directory, name, raw)
        existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(existing)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o600)
            or info.st_size != len(raw)
            or os.read(existing, 4097) != raw
        ):
            raise ValueError("Existing network attestation differs from accepted placement")
    finally:
        os.close(existing)


def require_private_directory(directory: int) -> None:
    info = os.fstat(directory)
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o700):
        raise ValueError("Private rootless runtime directory required")


def runtime_child(directory: int, component: str) -> int:
    require_private_directory(directory)
    try:
        os.mkdir(component, mode=0o700, dir_fd=directory)
        os.fsync(directory)
    except FileExistsError:
        pass
    return os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)


def initialize_runtime(
    root: str, name: str, attestation: PublicNetworkAttestation | None = None
) -> None:
    if not re.fullmatch(r"briareus-[a-f0-9]{48}", name, flags=re.ASCII):
        raise ValueError("Derived executor identity required")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in ("workers", name):
            child = runtime_child(directory, component)
            os.close(directory)
            directory = child
        require_private_directory(directory)
        if attestation is not None:
            write_attestation(directory, attestation)
    finally:
        os.close(directory)


def main() -> None:
    if os.geteuid() != 0:
        raise ValueError("Dedicated rootless initializer uid required")
    identity = expected_identity(os.environ)
    initialize("/workspace", identity)
    if "BRIAREUS_RUNTIME_WORKER" in os.environ:
        raw = os.environ.get("BRIAREUS_NETWORK_POLICY_ATTESTATION")
        attestation: PublicNetworkAttestation | None = None
        if raw is not None:
            if len(raw.encode()) > 4096:
                raise ValueError("Bounded network attestation required")
            attestation = decode_json(raw, PublicNetworkAttestation)
            validate_attestation(
                attestation,
                UUID(identity.node_uuid),
                UUID(identity.project_uuid),
                os.environ["BRIAREUS_RUNTIME_WORKER"],
            )
        initialize_runtime("/node-link", os.environ["BRIAREUS_RUNTIME_WORKER"], attestation)


if __name__ == "__main__":
    main()
