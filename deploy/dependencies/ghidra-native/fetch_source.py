"""Fetch the immutable public Ghidra MCP revision inside the image build."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPOSITORY = "https://github.com/ArthurKoba/ghidra-mcp.git"


def fetch_source(pin_path: Path, destination: Path) -> None:
    pin: object = json.loads(pin_path.read_text(encoding="utf-8"))
    if not isinstance(pin, dict) or pin.get("repository") != REPOSITORY:
        raise ValueError("Ghidra MCP must use the declared public source repository")
    revision = pin.get("revision")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Ghidra MCP source must identify an immutable Git revision")
    destination.mkdir(parents=True, exist_ok=False)
    commands = (
        ["git", "init", "--quiet", str(destination)],
        ["git", "-C", str(destination), "remote", "add", "origin", REPOSITORY],
        ["git", "-C", str(destination), "fetch", "--quiet", "--depth", "1", "origin", revision],
        ["git", "-C", str(destination), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
    )
    for command in commands:
        subprocess.run(command, check=True)
    actual = subprocess.check_output(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != revision:
        raise RuntimeError("Fetched Ghidra MCP source does not match its pinned revision")
    print(f"Verified public Ghidra MCP source revision {revision}")


if __name__ == "__main__":
    fetch_source(Path("/source.json"), Path("/vendor"))
