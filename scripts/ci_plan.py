from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

NATIVE_BUILD_HELPER = "deploy/dependencies/ghidra-native/fetch_source.py"

FULL_TRIGGERS = (
    ".github/workflows/",
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yaml",
    "pyproject.toml",
    "uv.lock",
    "docker-entrypoint.sh",
    "scripts/ci_plan.py",
    "scripts/validate_compose.py",
    "scripts/bri_dockerfiles.py",
    "src/common/",
)


@dataclass(frozen=True)
class Area:
    source_prefixes: tuple[str, ...]
    mypy_paths: tuple[str, ...]


AREAS: dict[str, Area] = {
    "auth": Area(("src/auth_service/",), ("src/auth_service",)),
    "gateway": Area(("src/gateway/",), ("src/gateway",)),
    "control-panel-api": Area(("src/control_panel_api/",), ("src/control_panel_api",)),
    "chromium": Area(("src/browser_runtime/",), ("src/browser_runtime",)),
    "github": Area(("src/modules/github/",), ("src/modules/github",)),
    "gitlab": Area(("src/modules/gitlab/",), ("src/modules/gitlab",)),
    "files": Area(("src/modules/files/",), ("src/modules/files",)),
    "web": Area(("src/modules/web/",), ("src/modules/web",)),
    "terminal": Area(("src/modules/terminal/",), ("src/modules/terminal",)),
    "analysis": Area(("src/modules/analysis/",), ("src/modules/analysis",)),
    "ghidra": Area(("src/modules/ghidra/",), ("src/modules/ghidra",)),
    "ghidra-build": Area((NATIVE_BUILD_HELPER,), (NATIVE_BUILD_HELPER,)),
    "observability": Area(
        ("src/modules/signoz/", "src/modules/coolify/", "src/modules/observability/"),
        ("src/modules/signoz", "src/modules/coolify", "src/modules/observability"),
    ),
}

CONTRACTS: dict[str, tuple[str, ...]] = {
    "auth": (
        "test_bri_identity_provider",
        "test_bri_mcp_refresh",
        "test_bri_mcp_revocation",
        "test_bri_gateway_tokens",
    ),
    "gateway": ("test_bri_gateway_tokens", "test_bri_proxy_sessions"),
    "control-panel-api": (
        "test_bri_postgres",
        "test_bri_panel_identity",
        "test_bri_proxy_sessions",
        "test_bri_websocket_authority",
    ),
    "chromium": ("test_bri_browser_contracts",),
    "web": ("test_bri_external_browser", "test_bri_browser_contracts"),
    "github": ("test_bri_operational_integrity",),
    "gitlab": ("test_bri_operational_integrity",),
    "files": ("test_bri_operational_integrity",),
    "analysis": ("test_bri_operational_integrity",),
    "observability": ("test_bri_operational_integrity",),
}
ALL_CONTRACTS = (
    *dict.fromkeys(module for modules in CONTRACTS.values() for module in modules),
    "test_bri_deployment_boundaries",
    "test_bri_coolify_packaging",
)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix)


def _contract_modules(paths: list[str], areas: list[str]) -> list[str]:
    modules = [module for name in areas for module in CONTRACTS.get(name, ())]
    for path in paths:
        if path.startswith("tests/") and path.endswith(".py"):
            name = Path(path).stem
            modules.extend((name,) if name in ALL_CONTRACTS else ALL_CONTRACTS)
        elif path.startswith("deploy/") or path in {
            "scripts/bri_catalog.py",
            "scripts/bri_local.py",
            "scripts/bri_coolify.py",
        }:
            modules.extend(("test_bri_deployment_boundaries", "test_bri_coolify_packaging"))
    return _unique(modules)


def _changed_areas(paths: list[str]) -> tuple[list[str], bool]:
    matched: list[str] = []
    unknown = False
    for path in paths:
        owner = next(
            (
                name
                for name, area in AREAS.items()
                if any(_matches(path, prefix) for prefix in area.source_prefixes)
            ),
            None,
        )
        if owner and owner not in matched:
            matched.append(owner)
        elif path.startswith("src/") and not owner:
            unknown = True
    return matched, unknown


def plan(changed_paths: list[str], *, force_full: bool = False) -> dict[str, object]:
    paths: list[str] = []
    for raw_path in changed_paths:
        value = raw_path.strip()
        if not value:
            continue
        paths.append(value[2:] if value.startswith("./") else value)
    full = (
        force_full
        or not paths
        or any(_matches(path, trigger) for path in paths for trigger in FULL_TRIGGERS)
    )

    matched_areas, unknown_code = _changed_areas(paths)

    # Cross-cutting or unknown code changes are safer as a full gate.
    if unknown_code or len(matched_areas) >= 4:
        full = True

    if full:
        return {
            "full": True,
            "compose": True,
            "areas": ["full"],
            "mypy_paths": ["src", NATIVE_BUILD_HELPER],
            "ruff_paths": ["src", "scripts", "tests", NATIVE_BUILD_HELPER],
            "contract_modules": list(ALL_CONTRACTS),
        }

    mypy_paths: list[str] = []
    for name in matched_areas:
        area = AREAS[name]
        mypy_paths.extend(area.mypy_paths)

    changed_python = [path for path in paths if path.endswith(".py") and Path(path).parts]
    return {
        "full": False,
        "compose": any(path.startswith("deploy/") for path in paths),
        "areas": matched_areas or ["non-code"],
        "mypy_paths": _unique(mypy_paths),
        "ruff_paths": _unique(changed_python),
        "contract_modules": _contract_modules(paths, matched_areas),
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
