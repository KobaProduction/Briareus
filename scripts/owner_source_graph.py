"""Exact static Python owner source and import graph for native uv-only images.

Build-time AST closure only; no Python package, wheel, artifact installation,
network, Docker, runtime database, or external release side effects.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_OWNER_ENTRY = {
    "identity": "identity.platform_runtime",
    "access": "authorization.platform_runtime",
    "platform": "projects.control_runtime",
    "resources": "projects.catalog_runtime",
}
_OWNED_ROOTS = {
    "common",
    "identity",
    "authorization",
    "projects",
    "agents",
    "teams",
    "source_control",
}
_SOURCE_CONTROL_PUBLIC = (
    ("source_control", "hands/svc/src/source_control/__init__.py"),
    ("source_control.operations", "hands/svc/src/source_control/operations.py"),
)
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
_OWNER_ALLOWED_ROOTS: dict[str, frozenset[str]] = {
    "identity": frozenset({"common", "service_runtime", "owner_protocol", "identity"}),
    "access": frozenset({"common", "service_runtime", "owner_protocol", "authorization"}),
    "platform": frozenset(
        {"common", "service_runtime", "owner_protocol", "projects", "teams", "agents"}
    ),
    "resources": frozenset({"common", "service_runtime", "owner_protocol", "projects"}),
}


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class SourceIndex:
    modules: dict[str, Path]


@dataclass(frozen=True)
class ModelRegistrations:
    by_owner: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ImportDependencies:
    internal: set[str]
    external: set[str]


@dataclass(frozen=True)
class OwnerClosure:
    paths: set[str]
    external: list[str]


@dataclass(frozen=True)
class SourceGraph:
    schema: str
    producer_sha256: str
    build_input_paths: list[str]
    entrypoints: dict[str, str]
    private_source_surfaces: dict[str, tuple[str, ...]]
    dynamic_owner_model_modules: dict[str, tuple[str, ...]]
    third_party_import_roots: dict[str, list[str]]
    units: dict[str, list[SourceFile]]
    consumer_impact: dict[str, list[str]]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _index_source_root(source_root: Path, allowed: set[str], index: SourceIndex) -> None:
    for path in sorted(source_root.glob("**/*.py")):
        relative = path.relative_to(source_root)
        if relative.parts[0] not in allowed or any(
            part in {".venv", "__pycache__"} for part in relative.parts
        ):
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError("unsafe Python source path")
        parts = relative.with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        if name in index.modules:
            raise ValueError(f"ambiguous Python owner module {name}")
        index.modules[name] = path


def source_modules(root: Path) -> SourceIndex:
    index = SourceIndex({})
    for directory, allowed in (
        (root / "services", _OWNED_ROOTS),
        (root / "shared", {"service_runtime", "owner_protocol", "project_runtime_client"}),
    ):
        _index_source_root(directory, allowed, index)
    for module, relative in _SOURCE_CONTROL_PUBLIC:
        path = root / relative
        if not path.is_file() or path.is_symlink() or module in index.modules:
            raise ValueError("Exact public Source Control contract required")
        index.modules[module] = path
    return index


def _model_registration(key: ast.expr | None, pair: ast.expr) -> tuple[str, tuple[str, ...]]:
    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
        raise ValueError("dynamic owner key is not reviewed literal")
    if not isinstance(pair, ast.Tuple) or len(pair.elts) != 2:
        raise ValueError("dynamic owner model registration changed")
    value = pair.elts[1]
    if not isinstance(value, ast.Tuple):
        raise ValueError("dynamic owner model imports changed")
    parsed: list[str] = []
    for node in value.elts:
        item: object = ast.literal_eval(node)
        if not isinstance(item, str):
            raise ValueError("unknown dynamic owner import")
        parsed.append(item)
    return key.value, tuple(parsed)


def dynamic_model_modules(root: Path) -> ModelRegistrations:
    """Parse literal registrations without importing owner model code."""
    text = (root / "services/common/owner_registry.py").read_text(encoding="utf-8")
    result: dict[str, tuple[str, ...]] = {}
    for statement in ast.parse(text).body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name) or statement.target.id != "_OWNER_MODELS":
            continue
        if not isinstance(statement.value, ast.Dict):
            break
        for key, pair in zip(statement.value.keys, statement.value.values, strict=True):
            name, modules = _model_registration(key, pair)
            result[name] = modules
    if not set(_OWNER_ENTRY) <= set(result):
        raise ValueError("missing explicit owner SQL model source registrations")
    return ModelRegistrations(result)


class _Imports(ast.NodeVisitor):
    def __init__(self, name: str, package: str, known: set[str]) -> None:
        self.name = name
        self.package = package
        self.known = known
        self.found: set[str] = set()
        self.external: set[str] = set()

    def accept(self, module: str) -> None:
        if module in self.known:
            self.found.add(module)
        elif module.split(".", 1)[0] in _OWNED_ROOTS:
            raise ValueError(f"{self.name} references absent owner module {module}")
        else:
            self.external.add(module.split(".", 1)[0])

    def visit_If(self, node: ast.If) -> None:
        if (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING") or (
            isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"
        ):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for value in node.names:
            self.accept(value.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (
            importlib.util.resolve_name("." * node.level + (node.module or ""), self.package)
            if node.level
            else node.module or ""
        )
        if not root:
            raise ValueError(f"invalid import in {self.name}")
        self.accept(root)
        for imported in node.names:
            if f"{root}.{imported.name}" in self.known:
                self.found.add(f"{root}.{imported.name}")


def module_imports(path: Path, name: str, known: set[str]) -> ImportDependencies:
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    imports = _Imports(name, package, known)
    imports.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    external = imports.external - sys.stdlib_module_names - set(sys.builtin_module_names)
    return ImportDependencies(imports.found, external)


def _permitted_owner_module(owner: str, name: str) -> bool:
    if name in {"project_runtime_client", "project_runtime_client._lazy_exports"}:
        return True
    if name.split(".", 1)[0] in _OWNER_ALLOWED_ROOTS[owner]:
        return True
    return owner in {"access", "resources"} and name in {
        module for module, _path in _SOURCE_CONTROL_PUBLIC
    }


def _owner_closure(root: Path, owner: str, pending: list[str], index: SourceIndex) -> OwnerClosure:
    selected: set[str] = set()
    third: set[str] = set()
    known = set(index.modules)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in known:
            raise ValueError(f"{owner} dynamic source missing: {name}")
        selected.add(name)
        dependencies = module_imports(index.modules[name], name, known)
        third.update(dependencies.external)
        pending.extend(dependencies.internal - selected)
        parts = name.split(".")
        pending.extend(
            ".".join(parts[:count])
            for count in range(1, len(parts))
            if ".".join(parts[:count]) in known
        )
    forbidden = sorted(name for name in selected if not _permitted_owner_module(owner, name))
    if forbidden:
        raise ValueError(f"{owner} imports foreign bounded owner source: {forbidden}")
    return OwnerClosure(
        {index.modules[name].relative_to(root).as_posix() for name in selected}, sorted(third)
    )


def _partition_sources(root: Path, closures: Mapping[str, OwnerClosure]) -> SourcePartitions:
    common = set.intersection(*(entry.paths for entry in closures.values()))
    common = {path for path in common if path.startswith("services/common/")}
    common.add("services/common/__init__.py")
    shared = {
        path
        for closure in closures.values()
        for path in closure.paths
        if path.startswith(
            ("shared/service_runtime/", "shared/owner_protocol/", "shared/project_runtime_client/")
        )
    }
    owners: dict[str, set[str]] = {"common": common | shared}
    for owner in _OWNER_ENTRY:
        if not common <= closures[owner].paths:
            raise ValueError("shared API has not been reached by all four owners")
        directory = root / "scripts/alembic_owners" / owner
        if not (directory / "env.py").is_file():
            raise ValueError(f"{owner} frozen migration history unavailable")
        migrations = {
            path.relative_to(root).as_posix()
            for path in directory.rglob("*.py")
            if path.is_file() and not path.is_symlink()
        }
        owners[owner] = (closures[owner].paths - common - shared) | migrations
    return SourcePartitions(owners)


@dataclass(frozen=True)
class SourcePartitions:
    by_owner: dict[str, set[str]]


def source_closure(
    root: Path,
    *,
    producer: str = "scripts/owner_source_graph.py",
    private_surfaces: Mapping[str, tuple[str, ...]] | None = None,
) -> SourceGraph:
    surfaces = dict(_OWNER_SOURCE_SURFACES if private_surfaces is None else private_surfaces)
    index = source_modules(root)
    models = dynamic_model_modules(root)
    closures = {
        owner: _owner_closure(
            root, owner, [entry, *models.by_owner[owner], *surfaces[owner]], index
        )
        for owner, entry in _OWNER_ENTRY.items()
    }
    partitions = _partition_sources(root, closures)
    inventories = {
        unit: [SourceFile(path, digest((root / path).read_bytes())) for path in sorted(files)]
        for unit, files in partitions.by_owner.items()
    }
    consumers: dict[str, list[str]] = {}
    for unit, entries in inventories.items():
        for item in entries:
            consumers.setdefault(item.path, []).append(unit)
    producers = list(dict.fromkeys([producer, "scripts/owner_source_graph.py"]))
    for source in producers:
        consumers[source] = ["common", *_OWNER_ENTRY]
    for path, units in consumers.items():
        if path.startswith("scripts/alembic_owners/") and units != [path.split("/")[2]]:
            raise ValueError(f"cross-owner Alembic resource: {path}")
    return SourceGraph(
        "briareus-owner-source-closure-v1",
        digest(b"".join((root / source).read_bytes() for source in producers)),
        producers,
        dict(_OWNER_ENTRY),
        surfaces,
        models.by_owner,
        {owner: closure.external for owner, closure in closures.items()},
        inventories,
        consumers,
    )
