"""Run independent gates and preserve complete diagnostics under ignored artifacts/."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

from selection import ROOT, owner, source_owner

REPORTS = ROOT / "artifacts/quality"


@dataclass(frozen=True)
class Result:
    name: str
    status: int
    seconds: float
    log: str


def executable(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise ValueError(f"Required executable not found: {name}")
    return command


def run(
    name: str, command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> Result:
    REPORTS.mkdir(parents=True, exist_ok=True)
    log = REPORTS / (name.replace("/", "_") + ".log")
    started = time.monotonic()
    print(f"Checking {name}...", flush=True)
    with log.open("w", encoding="utf-8") as output:
        try:
            result = subprocess.run(  # noqa: S603 -- pinned tool argv, no shell or user source execution
                command,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
            )
            status = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            output.write(str(error))
            status = 2
    record = Result(name, status, round(time.monotonic() - started, 2), str(log.relative_to(ROOT)))
    print(f"  {'PASS' if status == 0 else 'FAIL'} ({record.seconds}s): {record.log}", flush=True)
    return record


@dataclass(frozen=True)
class Group:
    base: Path
    files: list[str]


@dataclass(frozen=True)
class Environment:
    values: dict[str, str]


def python_groups(paths: list[str], *, logical_sources: bool = False) -> list[Group]:
    groups: dict[Path, list[str]] = {}
    resolve_owner = source_owner if logical_sources else owner
    for path in paths:
        groups.setdefault(resolve_owner(path), []).append(path)
    return [Group(base, files) for base, files in groups.items()]


def owner_slug(base: Path) -> str:
    return "root" if base == ROOT else base.relative_to(ROOT).as_posix().replace("/", "_")


def python_lint(paths: list[str]) -> list[Result]:
    """Explicit Git paths include tracked source named build/ despite Ruff discovery defaults."""
    prefix = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--config",
        str(ROOT / "pyproject.toml"),
        "--output-format=json",
    ]
    batches: list[list[str]] = [[]]
    for path in paths:
        if sum(len(item) + 1 for item in batches[-1]) + len(path) > 20_000:
            batches.append([])
        batches[-1].append(path)
    return [
        run("ruff" if len(batches) == 1 else f"ruff-{index + 1}", prefix + batch)
        for index, batch in enumerate(batches)
        if batch
    ]


def python_source_root(base: Path) -> Path:
    if (base / "src").is_dir():
        return base / "src"
    return base.parent if (base / "__init__.py").is_file() else base


def python_type_command(project: Path) -> list[str]:
    """Discover owner SDKs and quality-only official stubs in one temporary overlay."""
    python_path = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    interpreter = project / ".venv" / python_path
    if not interpreter.is_file():
        return [sys.executable, "-m", "mypy"]
    command = [
        executable("uv"),
        "run",
        "--project",
        str(project),
        "--no-sync",
        "--no-env-file",
        "--python",
        str(interpreter),
    ]
    for package in ("mypy", "types-grpcio", "types-protobuf", "types-grpcio-health-checking"):
        command.extend(("--with", f"{package}=={version(package)}"))
    return [*command, "python", "-m", "mypy"]


def python_import_roots(source: Path) -> list[Path]:
    """Resolve bounded owner reuse packages after the selected owner's source root."""
    roots = [source, ROOT / "shared", ROOT / "services"]
    for owner_name in ("svc", "web", "infrastructure", "files"):
        dependency = ROOT / "hands" / owner_name / "src"
        if dependency.is_dir() and dependency not in roots:
            roots.append(dependency)
    return roots


def python_types(paths: list[str]) -> list[Result]:
    results: list[Result] = []
    for group in python_groups(paths, logical_sources=True):
        base, files = group.base, group.files
        source = python_source_root(base)
        env = os.environ.copy()
        env["MYPYPATH"] = os.pathsep.join(map(str, python_import_roots(source)))
        command = [
            *python_type_command(owner(files[0])),
            "--config-file",
            str(ROOT / "pyproject.toml"),
            "--explicit-package-bases",
            "--namespace-packages",
            "--follow-imports=silent",
        ]
        results.append(run("mypy-" + owner_slug(base), command + files, env=env))
    return results


def frontend(paths: list[str], full: bool) -> list[Result]:
    if not paths:
        return []
    ui = ROOT / "services/ui"
    bun = executable("bun")
    files = [
        str(Path(path).relative_to("services/ui"))
        for path in paths
        if Path(path).suffix in {".ts", ".tsx", ".js", ".mjs", ".vue", ".json", ".css", ".html"}
    ]
    targets = ["."] if full else files
    results = []
    if targets:
        results.append(
            run(
                "biome",
                [
                    bun,
                    "run",
                    "biome",
                    "lint",
                    "--error-on-warnings",
                    "--reporter=json",
                    "--max-diagnostics=none",
                    *targets,
                ],
                cwd=ui,
            )
        )
    results.append(
        run(
            "fsd",
            [bun, "run", "--bun", "steiger", "src", "--fail-on-warnings", "--reporter=json"],
            cwd=ui,
        )
    )
    results.append(run("vue-types", [bun, "run", "typecheck:all"], cwd=ui))
    return results


def test_environment(base: Path, tests: list[str]) -> Environment:
    env = os.environ.copy()
    roots = [base / "src", base, *python_import_roots(python_source_root(base))]
    if base in {ROOT / "services/authorization", ROOT / "services/platform"}:
        roots.append(ROOT / "services/api/src")
    if base == ROOT:
        roots.extend(
            (
                ROOT / "scripts",
                ROOT / "deploy",
                ROOT / "services/admin-api/src",
                ROOT / "services/external",
                ROOT / "hands/reverse/src",
                ROOT / "hands/terminal/src",
                ROOT / "hands/serena/src",
                ROOT / "hands/radare2/src",
            )
        )
    roots.extend(Path(path) if Path(path).is_dir() else Path(path).parent for path in tests)
    existing: list[Path] = []
    for path in roots:
        if path.is_dir() and path not in existing:
            existing.append(path)
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in existing)
    env.pop("VIRTUAL_ENV", None)
    return Environment(env)


def owner_test_paths(base: Path, files: list[str]) -> list[str]:
    roots = set()
    for path in files:
        parts = Path(path).parts
        if not path.endswith(".py"):
            continue
        if "tests" not in parts and not Path(path).name.startswith("test_"):
            continue
        if owner(path) != base:
            continue
        if "tests" in parts:
            roots.add(str(ROOT.joinpath(*parts[: parts.index("tests") + 1])))
        elif Path(path).name.startswith("test_"):
            roots.add(str(ROOT / path))
    return sorted(path for path in roots if Path(path).exists())


def impacted_owners(paths: list[str], files: list[str], full: bool) -> set[Path]:
    if full or any(path.startswith("shared/") for path in paths):
        return {
            owner(path)
            for path in files
            if path.endswith(".py") and ("/tests/" in path or Path(path).name.startswith("test_"))
        }
    return {owner(path) for path in paths if path.endswith(".py")}


def test_command(base: Path) -> list[str]:
    command = [
        executable("uv"),
        "run",
        "--project",
        str(base),
        "--frozen",
        "--no-env-file",
    ]
    packages = ["pytest==9.0.2", "pytest-asyncio==1.3.0", "httpx==0.28.1"]
    if base == ROOT:
        packages.extend(("grpcio==1.84.0", "grpcio-health-checking==1.84.0", "protobuf==7.36.2"))
    for package in packages:
        command.extend(("--with", package))
    return [*command, "python", "-m", "pytest", "-q", "--import-mode=importlib"]


def tests(paths: list[str], full: bool) -> list[Result]:
    all_files = (
        subprocess.check_output(  # noqa: S603 -- fixed Git inventory, no shell
            [executable("git"), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    impacted = impacted_owners(paths, all_files, full)
    results: list[Result] = []
    for base in sorted(impacted):
        test_paths = owner_test_paths(base, all_files)
        if not test_paths:
            continue
        results.append(
            run(
                "tests-" + owner_slug(base),
                test_command(base) + test_paths,
                cwd=base,
                env=test_environment(base, test_paths).values,
            )
        )
    if full or any(path.startswith("services/ui/") for path in paths):
        results.append(
            run("tests-ui", [executable("bun"), "run", "test"], cwd=ROOT / "services/ui")
        )
    return results


def summary(results: list[Result], checks: str) -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"summary-{checks}.json").write_text(
        json.dumps([asdict(item) for item in results], indent=2), encoding="utf-8"
    )
    return int(any(item.status != 0 for item in results))
