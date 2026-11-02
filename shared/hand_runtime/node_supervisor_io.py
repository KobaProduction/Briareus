"""Native self-process attestation and one approved private Unix listener."""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .node_supervisor_domain import SupervisorPath, SupervisorSandbox


def require_supervisor_sandbox() -> None:
    facts = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    mapping = Path("/proc/self/uid_map").read_text().splitlines()
    if not mapping:
        raise ValueError("Dedicated rootless supervisor placement required")
    SupervisorSandbox(
        os.geteuid(),
        facts.get("NoNewPrivs", "").strip() == "1",
        int(facts["CapEff"].strip(), 16),
        bool(os.statvfs("/").f_flag & os.ST_RDONLY),
        int(mapping[0].split()[1]),
    ).require_isolated()


@contextmanager
def supervisor_listener(module: str) -> Iterator[socket.socket]:
    directory = "/" + module + "-link"
    parent = os.lstat(directory)
    SupervisorPath(parent.st_mode, parent.st_uid).require_directory()
    path = directory + "/mcp.sock"
    try:
        previous = os.lstat(path)
    except FileNotFoundError:
        previous = None
    if previous is not None:
        SupervisorPath(previous.st_mode, previous.st_uid).require_replaceable_socket()
        os.unlink(path)
    os.umask(0o077)
    listener = socket.socket(socket.AF_UNIX)
    try:
        listener.bind(path)
        os.chmod(path, 0o600)
        listener.listen(32)
        yield listener
    finally:
        listener.close()
