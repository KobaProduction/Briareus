"""Full packaged Serena startup with an empty disposable workspace.

This verifies native startup, not Core/Rauthy/Cedar admission.
"""

import json
import os
import signal
import socket
import subprocess
import threading
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from serena_hand.node_server import create_app

from hand_runtime.node_adapter import run_node_app
from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount


def deployment() -> Deployment:
    public = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return Deployment(
        id=uuid4(),
        node_uuid=uuid4(),
        project_uuid=uuid4(),
        release=ModuleRelease(
            module="serena",
            image=os.environ["AUDIT_SERENA_IMAGE"],
            lifecycle="sessionful",
        ),
        limits=ResourceLimits(memory_bytes=1024**3, cpu_millis=500, pids=128),
        effect_verify_key=public,
        workspace=WorkspaceMount(id=uuid4(), read_only=False),
    )


def ready() -> bool:
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect("/serena-link/mcp.sock")
            connection.sendall(b"GET /health/ready HTTP/1.0\r\nHost: localhost\r\n\r\n")
            with connection.makefile("rb") as response:
                status = response.readline(128)
            return status.split(b" ", 2)[1] == b"200"
    except (OSError, IndexError):
        return False


def main() -> None:
    os.environ["BRIAREUS_DEPLOYMENT"] = deployment().model_dump_json()
    outcome: list[bool] = []

    def probe() -> None:
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                if ready():
                    outcome.append(True)
                    return
                time.sleep(1)
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=probe, daemon=True).start()
    run_node_app(create_app, "serena")
    assert outcome, "Actual Serena empty-workspace startup did not become ready"
    # The server has closed its UID watchdog before this read-only fixture probe.
    checked = subprocess.run(
        [
            "/usr/local/bin/python",
            "-S",
            "-c",
            'from pathlib import Path; assert list(Path("/project-data").iterdir()) == []',
        ],
        user=1000,
        group=1000,
        extra_groups=[],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr.decode(errors="replace")
    print(
        json.dumps(
            {
                "outcome": "passed",
                "scope": "full-packaged-Serena-empty-startup",
                "workspace_files": 0,
                "fake_project": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
