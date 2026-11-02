"""Exact source-file closure and per-owner Hatch wheel staging for D5.

One common ABI wheel and four independently versioned, source-derived owner
wheels. Generated artifacts live in local/ OUTSIDE Git. No Docker, DB, CI,
credentials, network access, published release, or foreign-owned source edits.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from owner_source_graph import (
    SourceFile,
    SourceGraph,
    module_imports,
    source_modules,
)
from owner_source_graph import (
    digest as _digest,
)
from owner_source_graph import (
    source_closure as build_source_closure,
)

_IMPORT_DISTS: dict[str, tuple[str, ...]] = {
    "alembic": ("alembic",),
    "cryptography": ("cryptography",),
    "fastapi": ("fastapi",),
    "jwt": ("pyjwt",),
    "opentelemetry": ("opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"),
    "pydantic": ("pydantic",),
    "pydantic_settings": ("pydantic-settings",),
    "sqlalchemy": ("sqlalchemy",),
    "starlette": ("fastapi",),
    "valkey": ("valkey",),
}
_OWNER_RUNTIME_DISTS = frozenset({"asyncpg", "uvicorn"})

_OWNER_SOURCE_SURFACES: dict[str, tuple[str, ...]] = {
    "identity": (
        "identity._service",
        "identity._account_source",
        "identity._user_delete_source",
        "identity._owner_proof_reader",
        "identity._effect_issuer",
        "identity.private_login_source",
        "identity._private_user_session",
        "identity._private_current_user",
        "identity._private_onboarding",
    ),
    "access": (
        "authorization._access_source",
        "authorization._access_proof_reader",
        "authorization._effect_issuer",
        "authorization._session_bootstrap_issuer",
        "authorization._team_access_issuer",
        "common.private_c2_operation",
    ),
    "platform": (
        "projects._control_source",
        "projects._team_source",
        "projects._control_proof_reader",
        "projects._effect_issuer",
        "projects._team_proof_reader",
        "projects._control_bff_source",
        "projects._scoped_owner_source",
    ),
    "resources": ("projects._catalog_source", "projects._catalog_lifecycle"),
}


def source_closure(root: Path) -> SourceGraph:
    return build_source_closure(
        root, producer="scripts/owner_packages.py", private_surfaces=_OWNER_SOURCE_SURFACES
    )


@dataclass(frozen=True)
class PinnedRequirements:
    by_name: dict[str, str]


def _pinned_requirements(root: Path) -> PinnedRequirements:
    source = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = source["project"]["dependencies"]
    pinned: dict[str, str] = {}
    for requirement in dependencies:
        if not isinstance(requirement, str):
            raise ValueError("invalid root requirement")
        base = requirement.split("[", 1)[0]
        for operator in ("<", ">", "=", "!", "~"):
            base = base.split(operator, 1)[0]
        key = base.strip().lower().replace("_", "-")
        if key in pinned:
            raise ValueError(f"ambiguous requirement {key}")
        pinned[key] = requirement
    return PinnedRequirements(pinned)


def _owner_third_party(root: Path, unit: str, files: list[SourceFile]) -> list[str]:
    all_modules = source_modules(root).modules
    roots: set[str] = set()
    for item in files:
        path = item.path
        if not path.startswith(
            (
                "services/",
                "shared/service_runtime/",
                "shared/owner_protocol/",
                "shared/project_runtime_client/",
                "hands/svc/src/source_control/",
            )
        ):
            continue
        relative = Path(*Path(path).parts[3 if path.startswith("hands/svc/src/") else 1 :])
        parts = relative.with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        imports = module_imports(root / path, module, set(all_modules))
        roots.update(imports.external)
    expected: set[str] = set()
    for imported in roots:
        if imported not in _IMPORT_DISTS:
            raise ValueError(f"{unit} depends on unmapped third-party module {imported}")
        expected.update(_IMPORT_DISTS[imported])
    if unit != "common":
        expected.update(_OWNER_RUNTIME_DISTS)
    pinned = _pinned_requirements(root).by_name
    if expected - set(pinned):
        raise ValueError(f"{unit} misses root pinned distributions {expected - set(pinned)}")
    return [pinned[name] for name in sorted(expected)]


def _package_destination(source: str) -> Path:
    path = Path(source)
    if source.startswith("hands/svc/src/source_control/"):
        return Path(*path.parts[3:])
    if path.parts[0] == "services":
        return Path(*path.parts[1:])
    if path.parts[:2] in {
        ("shared", "service_runtime"),
        ("shared", "owner_protocol"),
        ("shared", "project_runtime_client"),
    }:
        return Path(*path.parts[1:])
    if path.parts[:2] != ("scripts", "alembic_owners"):
        raise ValueError("owner package path outside reviewed source")
    return Path("common/alembic_owners", *path.parts[2:])


def _stage(root: Path, destination: Path, graph: SourceGraph) -> None:
    if destination.exists():
        raise FileExistsError("source package staging is immutable")
    inventories = graph.units
    destination.mkdir(parents=True)
    producer_sha = graph.producer_sha256
    common_sha = _digest(
        json.dumps([asdict(item) for item in inventories["common"]], sort_keys=True).encode()
        + producer_sha.encode()
    )
    common_version = f"0.1.0+pkg.s{common_sha[:16]}"
    for unit, files in inventories.items():
        folder = destination / unit
        folder.mkdir()
        source_sha = _digest(
            json.dumps([asdict(item) for item in files], sort_keys=True).encode()
            + producer_sha.encode()
        )
        version = common_version if unit == "common" else f"0.1.0+pkg.s{source_sha[:16]}"
        name = "briareus-owner-common" if unit == "common" else f"briareus-owner-{unit}"
        for item in files:
            original = root / item.path
            inside = _package_destination(item.path)
            final = folder / "src" / inside
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, final)
        requires = _owner_third_party(root, unit, files)
        if unit != "common":
            requires.append(f"briareus-owner-common=={common_version}")
        lines = [
            "[project]",
            f'name = "{name}"',
            f'version = "{version}"',
            'requires-python = ">=3.13"',
            f"dependencies = {json.dumps(requires)}",
            "[build-system]",
            'requires = ["hatchling"]',
            'build-backend = "hatchling.build"',
            "[tool.hatch.build.targets.wheel]",
            'only-include = ["src"]',
            "[tool.hatch.build.targets.wheel.sources]",
            '"src" = ""',
        ]
        (folder / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (folder / "release_receipt.json").write_text(
            json.dumps(
                {
                    "distribution": name,
                    "version": version,
                    "source_sha256": source_sha,
                    "source_files": [asdict(item) for item in files],
                    "dependencies": requires,
                    "common_dependency": common_version if unit != "common" else None,
                    "published_git_tree": None,
                    "review_state": "SOURCE_ONLY_UNPUBLISHED",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    (destination / "owner_source_graph.json").write_text(
        json.dumps(asdict(graph), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    graph = source_closure(args.root.resolve())
    if args.stage is not None:
        _stage(args.root.resolve(), args.stage.resolve(), graph)
    inventories = graph.units
    impact = graph.consumer_impact
    print(
        json.dumps(
            {
                "schema": graph.schema,
                "paths_per_unit": {key: len(items) for key, items in inventories.items()},
                "owner_migrations": [
                    path for path in impact if path.startswith("scripts/alembic_owners/")
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
