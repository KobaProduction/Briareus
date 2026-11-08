"""Run owner-scoped contracts from the monorepo with frozen dependencies."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "briareus-v1-contracts:local"
TARGETED = (
    "test_briareus_external_browser",
    "test_briareus_browser_contracts",
    "test_briareus_websocket_authority",
    "test_briareus_proxy_sessions",
)


def source_roots() -> tuple[Path, ...]:
    patterns = (
        "services/*/src/*/__init__.py",
        "services/control-panel/*/src/*/__init__.py",
        "services/hands/*/src/*/__init__.py",
        "services/hands/*/*/src/*/__init__.py",
        "services/dependencies/*/src/*/__init__.py",
        "shared/*/src/*/__init__.py",
        "shared/*/*/src/*/__init__.py",
        "shared/*/*/*/src/*/__init__.py",
    )
    return tuple(
        sorted({path.parent.parent for pattern in patterns for path in ROOT.glob(pattern)})
    )


def test_directories() -> tuple[Path, ...]:
    patterns = (
        "services/*/tests/test_*.py",
        "services/control-panel/*/tests/test_*.py",
        "services/hands/*/tests/test_*.py",
        "services/hands/*/*/tests/test_*.py",
        "services/dependencies/*/tests/test_*.py",
        "shared/**/tests/test_*.py",
        "tests/**/test_*.py",
    )
    return tuple(sorted({path.parent for pattern in patterns for path in ROOT.glob(pattern)}))


def contract_modules() -> tuple[str, ...]:
    paths = [path for directory in test_directories() for path in directory.glob("test_*.py")]
    names = [path.stem for path in paths]
    if len(names) != len(set(names)):
        raise ValueError("Contract module names must be unique across service owners")
    return tuple(sorted(names))


@dataclass(frozen=True)
class Selection:
    all_tests: bool
    modules: tuple[str, ...]


def selection() -> tuple[Selection, bool]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="One final aggregate test boundary")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("modules", nargs="*")
    args = parser.parse_args()
    if args.all and args.modules:
        parser.error("--all cannot be combined with targeted module names")
    return Selection(args.all, tuple(args.modules or TARGETED)), args.inside


def dependency_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in ("Dockerfile", "pyproject.toml", "uv.lock"):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def clean_snapshot() -> None:
    snapshot = ROOT / ".local/briareus-contracts/source"
    if snapshot.exists():
        if not snapshot.resolve().is_relative_to((ROOT / ".local/briareus-contracts").resolve()):
            raise ValueError("Contract snapshot escaped its owned directory")
        shutil.rmtree(snapshot)


def source_snapshot() -> Path:
    """Expose source inputs without host caches, credentials or UI dependencies."""
    snapshot = ROOT / ".local/briareus-contracts/source"
    clean_snapshot()
    snapshot.mkdir(parents=True)
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    allowed = {"services", "shared", "tests", "scripts", "deploy", "assets"}
    for relative in set(result.stdout.decode().split("\0")):
        path = Path(relative)
        if not relative or (
            path.parts[0] not in allowed
            and relative
            not in {
                "Dockerfile",
                "pyproject.toml",
                "uv.lock",
                "docker-compose.yaml",
            }
        ):
            continue
        source = ROOT / path
        if not source.is_file() or source.is_symlink():
            continue
        if any(part in {"node_modules", ".venv", ".local", "__pycache__"} for part in path.parts):
            continue
        if source.name == ".env" or (
            source.name.startswith(".env.") and source.name != ".env.example"
        ):
            continue
        target = snapshot / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return snapshot


def docker_command(requested: Selection) -> list[str]:
    fingerprint = dependency_fingerprint()
    inspection = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            IMAGE,
            "--format",
            '{{index .Config.Labels "briareus.dependency-source"}}',
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if inspection.returncode or inspection.stdout.strip() != fingerprint:
        subprocess.run(
            [
                "docker",
                "build",
                "--label",
                f"briareus.dependency-source={fingerprint}",
                "--tag",
                IMAGE,
                "--file",
                "Dockerfile",
                ".",
            ],
            cwd=ROOT,
            check=True,
        )
    snapshot = source_snapshot()
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--mount",
        f"type=bind,source={snapshot},target=/work,readonly",
        "--workdir",
        "/work",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "DEPLOYMENT_ENVIRONMENT=test",
        "--env",
        "VALKEY_PASSWORD=briareus-contract-test-only",
        "--entrypoint",
        "/app/.venv/bin/python",
        IMAGE,
        "-c",
        (
            "import os, runpy, shutil, sys; "
            "from pathlib import Path; "
            "destination = Path('/tmp/briareus-contract-source'); "
            "shutil.copytree('/work', destination); "
            "os.chdir(destination); "
            "sys.argv = [str(destination / 'tests/run_briareus_contracts.py'), "
            "'--inside', *sys.argv[1:]]; "
            "runpy.run_path(sys.argv[0], run_name='__main__')"
        ),
        *(("--all",) if requested.all_tests else requested.modules),
    ]


def run_inside(requested: Selection) -> int:
    paths = [ROOT, *source_roots(), *test_directories(), ROOT / "tests/support", ROOT / "scripts"]
    sys.path[:0] = [str(path) for path in paths]
    os.environ["DEPLOYMENT_ENVIRONMENT"] = "test"
    os.environ["VALKEY_PASSWORD"] = "briareus-contract-test-only"
    modules = contract_modules() if requested.all_tests else requested.modules
    available = set(contract_modules())
    if any(module.split(".")[0] not in available for module in modules):
        raise ValueError("Requested contract module does not belong to a service/test owner")
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main() -> int:
    requested, inside = selection()
    if inside:
        return run_inside(requested)
    label = "final aggregate" if requested.all_tests else ", ".join(requested.modules)
    print("Briareus validation: " + label, flush=True)
    if sys.platform == "win32":
        command = docker_command(requested)
    else:
        command = [
            "uv",
            "run",
            "--python",
            "3.13",
            "--frozen",
            "--no-env-file",
            "--group",
            "web",
            "--group",
            "quality",
            "python",
            "tests/run_briareus_contracts.py",
            "--inside",
            *(("--all",) if requested.all_tests else requested.modules),
        ]
    try:
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    finally:
        if sys.platform == "win32":
            clean_snapshot()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
