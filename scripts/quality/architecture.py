"""Direct Clean Architecture dependency guards; behavior/invariant review remains mandatory."""

from __future__ import annotations

import ast
from pathlib import Path

from contracts import Finding
from runner import python_source_root
from selection import ROOT, is_test, owner, source_owner

DOMAIN_EXTERNAL = frozenset(
    {
        "fastapi",
        "starlette",
        "sqlalchemy",
        "asyncpg",
        "httpx",
        "requests",
        "valkey",
        "redis",
        "pydantic",
        "pydantic_settings",
        "docker",
        "mcp",
        "fastmcp",
        "grpc",
        "uvicorn",
        "websockets",
        "playwright",
        "cedarpy",
        "cryptography",
        "jwt",
        "subprocess",
        "socket",
        "sqlite3",
    }
)
APPLICATION_EXTERNAL = DOMAIN_EXTERNAL - {"pydantic"}
LAYERS = ("domain", "application", "infrastructure", "presentation")
OUTER_PARTS = frozenset(
    {
        "infrastructure",
        "presentation",
        "adapters",
        "persistence",
        "controllers",
        "routers",
        "transport",
        "database",
    }
)


def layer_for(path: str) -> str | None:
    if is_test(path):
        return None
    relative = Path(path).relative_to(owner(path).relative_to(ROOT))
    parts = relative.parts
    if owner(path) == ROOT and parts[0] in {"services", "hands", "shared"}:
        parts = parts[2:]
    for part in parts[:-1]:
        if part in LAYERS:
            return part
    return "domain" if Path(path).stem.endswith("_domain") else None


def imported_modules(node: ast.AST, package: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    parent = package[: len(package) - node.level + 1] if node.level else ()
    module = (*parent, *(node.module or "").split("."))
    if node.module:
        return (".".join(part for part in module if part),)
    return tuple(".".join((*parent, alias.name)) for alias in node.names)


def dependency_forbidden(layer: str, module: str) -> bool:
    parts = module.split(".")
    blocked = DOMAIN_EXTERNAL if layer == "domain" else APPLICATION_EXTERNAL
    if parts[0] in blocked:
        return True
    # Legacy private modules are still adapters, e.g. ``owner._persistence``.
    normalized = {part.lstrip("_") for part in parts}
    if normalized & OUTER_PARTS:
        return True
    return layer == "domain" and "application" in normalized


def package_for(path: str) -> tuple[str, ...]:
    source_root = python_source_root(source_owner(path))
    return (ROOT / path).relative_to(source_root).parts[:-1]


def file_findings(path: str) -> list[Finding]:
    layer = layer_for(path)
    if layer is None or layer not in {"domain", "application"}:
        return []
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"), filename=path)
    package = package_for(path)
    imports = (node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
    return [
        Finding(
            path,
            node.lineno,
            "ARCH001",
            f"{layer} depends outward on {module}; define an inward port/DTO.",
        )
        for node in imports
        for module in imported_modules(node, package)
        if dependency_forbidden(layer, module)
    ]


def check(paths: list[str]) -> int:
    findings = [finding for path in paths for finding in file_findings(path)]
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.code} {finding.message}")
    return int(bool(findings))
