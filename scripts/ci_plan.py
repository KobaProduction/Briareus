from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FULL_TRIGGERS = (
    ".github/workflows/",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "scripts/ci_plan.py",
    "scripts/quality_gate.py",
    ".githooks/",
    "tests/run_briareus_contracts.py",
    "tests/support/",
)


@dataclass(frozen=True)
class Area:
    source_prefixes: tuple[str, ...]
    mypy_paths: tuple[str, ...]


def catalog_areas() -> dict[str, Area]:
    document = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    areas = {
        "auth": Area(
            ("shared/identity/token-verification/",), ("shared/identity/token-verification/src",)
        )
    }
    for service in document["services"]:
        directory = service["directory"]
        roots = tuple(
            sorted(
                {str(Path(owner).parent.as_posix()) for owner in service.get("source_owners", [])}
            )
        )
        areas[service["name"]] = Area((directory + "/",), roots)
    return areas


AREAS = catalog_areas()

CONTRACTS: dict[str, tuple[str, ...]] = {
    "auth": (
        "test_briareus_introspection",
        "test_briareus_oidc",
        "test_briareus_zitadel_tokens",
        "test_briareus_gateway_tokens",
    ),
    "gateway": ("test_briareus_gateway_tokens", "test_briareus_proxy_sessions"),
    "control-panel-api": (
        "test_briareus_postgres",
        "test_briareus_panel_tokens",
        "test_briareus_proxy_sessions",
        "test_briareus_websocket_authority",
    ),
    "server": (
        "test_briareus_operational_integrity",
        "test_briareus_server_mount",
        "test_briareus_server_audit",
    ),
    "dependencies": ("test_briareus_deployment_boundaries", "test_briareus_coolify_packaging"),
    "playwright": (
        "test_briareus_external_browser",
        "test_briareus_browser_contracts",
        "test_briareus_supervisor",
    ),
    "analysis": ("test_briareus_operational_integrity", "test_briareus_analyzer_proxy"),
    "analysis-g": ("test_briareus_operational_integrity", "test_briareus_analysis_direct_cleanup"),
    **dict.fromkeys(
        ("github", "gitlab", "radare2", "serena", "signoz", "coolify"),
        ("test_briareus_operational_integrity",),
    ),
}
DEPLOYMENT_CONTRACTS = (
    "test_briareus_deployment_boundaries",
    "test_briareus_coolify_packaging",
    "test_briareus_mcp_templates",
)


@lru_cache
def all_contracts() -> tuple[str, ...]:
    patterns = (
        "services/*/tests/test_*.py",
        "services/control-panel/*/tests/test_*.py",
        "services/hands/*/tests/test_*.py",
        "services/hands/*/*/tests/test_*.py",
        "services/dependencies/*/tests/test_*.py",
        "shared/**/tests/test_*.py",
        "tests/**/test_*.py",
    )
    return tuple(sorted({path.stem for pattern in patterns for path in ROOT.glob(pattern)}))


@lru_cache
def source_roots() -> tuple[str, ...]:
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
        sorted(
            {
                path.parent.parent.relative_to(ROOT).as_posix()
                for pattern in patterns
                for path in ROOT.glob(pattern)
            }
        )
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix)


def shared_consumers(path: str) -> tuple[str, ...]:
    from fnmatch import fnmatchcase

    document = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    return tuple(
        service["name"]
        for service in document["services"]
        if any(fnmatchcase(path, pattern) for pattern in service["watch_paths"])
    )


def path_owner(path: str) -> str | None:
    return next(
        (
            name
            for name, area in AREAS.items()
            if any(_matches(path, prefix) for prefix in area.source_prefixes)
        ),
        None,
    )


def changed_areas(paths: list[str]) -> tuple[list[str], bool]:
    matched: list[str] = []
    unknown_python = False
    for path in paths:
        owner = path_owner(path)
        if owner and "/tests/" not in path:
            matched.append(owner)
        elif path.startswith("shared/"):
            matched.extend(shared_consumers(path))
        elif owner is None and path.startswith("services/") and path.endswith(".py"):
            unknown_python = True
    return _unique(matched), unknown_python


def deployment_changed(path: str) -> bool:
    if path.startswith(("deploy/", "scripts/briareus_")):
        return True
    return path.startswith("services/") and (
        "docker-compose" in path or "Dockerfile" in path or path.endswith("requirements.lock")
    )


def selected_contracts(paths: list[str], areas: list[str], *, deployment: bool) -> list[str]:
    modules = [module for name in areas for module in CONTRACTS.get(name, ())]
    modules.extend(
        test.stem
        for name in areas
        if name in AREAS
        for prefix in AREAS[name].source_prefixes
        for test in (ROOT / prefix / "tests").glob("test_*.py")
    )
    if set(areas) & {"signoz", "coolify"}:
        modules.append("test_briareus_provider_isolation")
    if any(
        path.startswith(
            ("shared/control-panel/", "shared/policies/", "shared/control_panel_client/")
        )
        for path in paths
    ):
        modules.append("test_briareus_policy_clients")
    modules.extend(
        Path(path).stem
        for path in paths
        if path.endswith(".py") and Path(path).stem in all_contracts()
    )
    if deployment:
        modules.extend(DEPLOYMENT_CONTRACTS)
    return _unique(modules)


def full_plan() -> dict[str, object]:
    return {
        "postgres": True,
        "full": True,
        "compose": True,
        "areas": ["full"],
        "mypy_paths": list(source_roots()),
        "ruff_paths": ["services", "shared", "scripts", "tests"],
        "contract_modules": list(all_contracts()),
    }


def selected_mypy_paths(paths: list[str], areas: list[str]) -> list[str]:
    result = [value for name in areas if name in AREAS for value in AREAS[name].mypy_paths]
    result.extend(
        root
        for root in source_roots()
        if root.startswith("shared/")
        and any(path.startswith(root + "/") and path.endswith(".py") for path in paths)
    )
    return _unique(result)


def selected_ruff_paths(paths: list[str]) -> list[str]:
    return _unique([path for path in paths if path.endswith(".py") and (ROOT / path).is_file()])


def plan(changed_paths: list[str], *, force_full: bool = False) -> dict[str, object]:
    paths = [path.strip().removeprefix("./") for path in changed_paths if path.strip()]
    areas, unknown_python = changed_areas(paths)
    global_change = any(_matches(path, trigger) for path in paths for trigger in FULL_TRIGGERS)
    full = force_full or not paths or unknown_python or global_change
    if full:
        return full_plan()
    deployment = any(deployment_changed(path) for path in paths)
    return {
        "postgres": "control-panel-api" in areas
        or any(path.endswith("postgres_migrations.py") for path in paths),
        "full": False,
        "compose": deployment,
        "areas": areas or ["non-code"],
        "mypy_paths": selected_mypy_paths(paths, areas),
        "ruff_paths": selected_ruff_paths(paths),
        "contract_modules": selected_contracts(paths, areas, deployment=deployment),
    }


def _emit_github_output(result: dict[str, object], output_file: Path) -> None:
    lines = []
    for key, value in result.items():
        rendered = (
            json.dumps(value, separators=(",", ":"))
            if not isinstance(value, bool)
            else str(value).lower()
        )
        lines.append(f"{key}={rendered}")
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--force-full", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = plan(args.paths, force_full=args.force_full)
    if args.github_output:
        _emit_github_output(result, args.github_output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
