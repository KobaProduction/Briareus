"""Run the requested BRI contracts against the frozen Linux runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "bri-v1-runtime-base:local"
TARGETED = (
    "test_bri_external_browser",
    "test_bri_browser_contracts",
    "test_bri_websocket_authority",
    "test_bri_proxy_sessions",
)


@dataclass(frozen=True)
class Selection:
    all_tests: bool
    modules: tuple[str, ...]

    def arguments(self) -> tuple[str, ...]:
        if self.all_tests:
            return "discover", "-s", "tests", "-p", "test_*.py", "-v"
        return *self.modules, "-v"


def selection() -> Selection:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="One final aggregate test boundary")
    parser.add_argument("modules", nargs="*")
    args = parser.parse_args()
    if args.all and args.modules:
        parser.error("--all cannot be combined with targeted module names")
    return Selection(args.all, tuple(args.modules or TARGETED))


def dependency_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in ("Dockerfile", "pyproject.toml", "uv.lock"):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def docker_command(requested: Selection) -> list[str]:
    inspection = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            IMAGE,
            "--format",
            '{{index .Config.Labels "bri.dependency-source"}}',
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if inspection.returncode or inspection.stdout.strip() != dependency_fingerprint():
        raise RuntimeError(
            "The frozen BRI runtime image is missing or stale. "
            "Run python scripts/bri_local.py base before validation."
        )
    command = ["docker", "run", "--rm", "--network", "none"]
    for name in ("src", "tests", "scripts", "deploy"):
        command.extend(["--mount", f"type=bind,source={ROOT / name},target=/work/{name},readonly"])
    command.extend(
        [
            "--workdir",
            "/work",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONPATH=/work/src:/work/tests:/work/scripts",
            "--entrypoint",
            "/app/.venv/bin/python",
            IMAGE,
            "-m",
            "unittest",
            *requested.arguments(),
        ]
    )
    return command


def main() -> int:
    requested = selection()
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if sys.platform == "win32":
        command = docker_command(requested)
    else:
        environment["PYTHONPATH"] = os.pathsep.join(
            str(ROOT / name) for name in ("src", "tests", "scripts")
        )
        command = [
            "uv",
            "run",
            "--python",
            "3.13",
            "--frozen",
            "--no-env-file",
            "--group",
            "web",
            "python",
            "-m",
            "unittest",
            *requested.arguments(),
        ]
    print(
        "BRI validation: "
        + ("final aggregate" if requested.all_tests else ", ".join(requested.modules)),
        flush=True,
    )
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
