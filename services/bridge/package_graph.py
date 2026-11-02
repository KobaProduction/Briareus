"""R18-PKG reproducible, conservative Python runtime import-closure authority.

Build-time source auditor, NOT an MCP tool/OS service. D5 independently
consumes the manifest for Docker COPY, per-service uv installs, and native
Coolify watch generation. Unknown dynamic imports are reported explicitly,
not quietly omitted. Imports nested in runtime functions are included, while
TYPE_CHECKING imports are not executed. No live service is imported here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Never, TypedDict

_SERVICE_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    "gateway": ("bridge.server",),
    "files": ("modules.files.runtime",),
    "terminal": ("modules.terminal.runtime",),
    "web": ("modules.web.runtime",),
    # One private ASGI shell. Both source-owned GitHub/GitLab registries are
    # bundled for a future C2-authenticated composition but not mounted.
    "svc": ("modules.svc.runtime",),
    "infrastructure": ("modules.observability.runtime",),
    "reverse": ("modules.analysis.runtime",),
}
_VALID_RUNTIME = frozenset(_SERVICE_ENTRYPOINTS)
_OWNER_PACKAGE: dict[str, str] = {
    "gateway": "bridge",
    "files": "modules.files",
    "terminal": "modules.terminal",
    "web": "modules.web",
    "svc": "modules.svc;modules.github;modules.gitlab",
    "infrastructure": "modules.observability",
    "reverse": "modules.analysis",
}


@dataclass(frozen=True, slots=True)
class BoundedOwnerSource:
    owner: str
    package: str
    source: str


_BOUNDED_OWNER_SOURCES = (
    BoundedOwnerSource("svc", "source_control", "hands/svc/src/source_control"),
    BoundedOwnerSource("web", "web_runtime", "hands/web/src/web_runtime"),
    BoundedOwnerSource("files", "files_hand", "hands/files/src/files_hand"),
    BoundedOwnerSource(
        "infrastructure",
        "infrastructure_runtime",
        "hands/infrastructure/src/infrastructure_runtime",
    ),
)
_BOUNDED_IMPORT_ROOTS = frozenset(item.package for item in _BOUNDED_OWNER_SOURCES)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_name(path: Path, source: Path) -> str:
    parts = list(path.relative_to(source).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _type_only(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"
    )


@dataclass(frozen=True)
class Unit:
    name: str
    entrypoints: tuple[str, ...]
    source_paths: tuple[str, ...]
    runtime_package_paths: tuple[str, ...]
    shared_source_paths: tuple[str, ...]
    transitive_foreign_source_paths: tuple[str, ...]
    external_import_roots: tuple[str, ...]
    dynamic_imports: tuple[str, ...]
    hash_sha256: str


@dataclass(frozen=True)
class ExportBinding:
    public_name: str
    module_path: str


@dataclass(frozen=True)
class ModuleExports:
    module_name: str
    bindings: tuple[ExportBinding, ...]


@dataclass(frozen=True)
class OwnerLedgerCandidate:
    owner: str
    module_path: str


@dataclass(frozen=True)
class ProviderSourceHandler:
    provider: str
    module_name: str
    handler: str


@dataclass(frozen=True)
class ImportClosure:
    modules: frozenset[str]
    dynamic_imports: frozenset[str]
    external_import_roots: frozenset[str]


class SourceHandlerManifest(TypedDict):
    module: str
    handler: str


class ReleaseUnitManifest(TypedDict):
    entrypoints: list[str]
    startup_loader: str
    expected_asgi_app: str
    source_paths: list[str]
    owned_paths: list[str]
    shared_paths: list[str]
    cross_owner_imports: list[str]
    external_import_roots: list[str]
    dynamic_imports_to_review: list[str]
    dynamic_owner_ledger_candidates_not_included: dict[str, str]
    source_content_sha256: str
    public_transport_accepted: bool
    has_accepted_unified_entrypoint: bool
    source_only_transport_pending: bool
    source_provider_handlers: dict[str, SourceHandlerManifest]
    owner_alembic_histories: list[Never]
    excluded_unaccepted_source: list[str]


class ReleaseManifest(TypedDict):
    schema: str
    source_tool: str
    source_tool_sha256: str
    evidence: str
    release_units: dict[str, ReleaseUnitManifest]
    source_reverse_consumers: dict[str, list[str]]


class _Imports(ast.NodeVisitor):
    def __init__(
        self, module: str, *, is_package: bool, lazy_exports: dict[str, dict[str, str]]
    ) -> None:
        self.module = module
        self.base = module if is_package else module.rpartition(".")[0]
        self.lazy_exports = lazy_exports
        self._function: str | None = None
        self.names: set[str] = set()
        self.dynamic: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        previous = self._function
        self._function = node.name
        self.generic_visit(node)
        self._function = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        previous = self._function
        self._function = node.name
        self.generic_visit(node)
        self._function = previous

    def visit_If(self, node: ast.If) -> None:
        if not _type_only(node.test):
            for item in node.body:
                self.visit(item)
        for item in node.orelse:
            self.visit(item)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        prefix = self.base.split(".")
        if node.level:
            count = node.level - 1
            if count >= len(prefix):
                self.dynamic.add(f"{self.module}:invalid_relative_import:{node.lineno}")
                return
            prefix = prefix[: len(prefix) - count] if count else prefix
            base = ".".join((*prefix, *(node.module.split(".") if node.module else ())))
        else:
            base = node.module or ""
        if base:
            self.names.add(base)
        for item in node.names:
            if item.name == "*":
                self.dynamic.add(f"{self.module}:star_import:{base}:{node.lineno}")
                continue
            self.names.add(f"{base}.{item.name}")
            self._lazy_symbol(base, item.name)

    def _lazy_symbol(self, base: str, symbol: str) -> None:
        mapping = self.lazy_exports.get(base)
        if mapping is not None:
            mapped = mapping.get(symbol)
            if mapped is None:
                self.dynamic.add(f"{self.module}:unmapped_lazy_symbol:{base}.{symbol}")
            else:
                self.names.add(mapped)

    def _dynamic_import(self, node: ast.Call, name: str) -> None:
        if (
            (self.module in self.lazy_exports and self._function == "__getattr__")
            or (
                self.module == "project_runtime_client._lazy_exports"
                and self._function == "resolve"
                and bool({"modules.project_runtime", "projects"} & self.lazy_exports.keys())
            )
        ) and name == "import_module":
            # Accepted literal maps are resolved at the importing call-site.
            pass
        elif (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            item = node.args[0].value
            if item.startswith(".") and len(node.args) > 1:
                self.dynamic.add(f"{self.module}:relative_dynamic_import:{node.lineno}")
            elif not item.startswith("."):
                self.names.add(item)
        else:
            self.dynamic.add(f"{self.module}:nonliteral_dynamic_import:{node.lineno}")

    def visit_Call(self, node: ast.Call) -> None:
        name = ast.unparse(node.func)
        if name in {"import_module", "importlib.import_module", "__import__"}:
            self._dynamic_import(node, name)
        self.generic_visit(node)


def _export_expression(tree: ast.Module, module_name: str, variable: str) -> ast.expr | None:
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == variable
    ]
    if not values:
        if module_name == "modules.project_runtime":
            raise ValueError("Runtime typed lazy exports missing")
        return None
    if len(values) != 1 or values[0] is None:
        raise ValueError(f"ambiguous dynamic exports in {module_name}")
    return values[0]


def _assigned_values(tree: ast.Module, variable: str) -> tuple[ast.expr, ...]:
    return tuple(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets)
    )


def _declared_public_names(tree: ast.Module) -> tuple[ast.expr, ...]:
    return _assigned_values(tree, "__all__")


def _source_text(expression: ast.expr, failure: str) -> str:
    if not isinstance(expression, ast.Constant) or not isinstance(expression.value, str):
        raise ValueError(failure)
    return expression.value


def _source_bindings(expression: ast.expr, failure: str) -> tuple[tuple[str, ast.expr], ...]:
    if not isinstance(expression, ast.Dict):
        raise ValueError(failure)
    entries: dict[str, ast.expr] = {}
    for key, value in zip(expression.keys, expression.values, strict=True):
        if key is None:
            raise ValueError(failure)
        entries[_source_text(key, failure)] = value
    return tuple(entries.items())


def _source_names(expression: ast.expr, failure: str) -> set[str]:
    if not isinstance(expression, (ast.List, ast.Tuple, ast.Set)):
        raise ValueError(failure)
    return {_source_text(item, failure) for item in expression.elts}


def _export_binding(
    source: Path, module_name: str, public: str, destination: ast.expr
) -> ExportBinding:
    if not public.isidentifier():
        raise ValueError("invalid literal public symbol")
    if module_name == "projects":
        failure = "A16 Project owner symbol binding is not literal"
        if not isinstance(destination, ast.Tuple) or len(destination.elts) != 2:
            raise ValueError(failure)
        module_path = _source_text(destination.elts[0], failure)
        if _source_text(destination.elts[1], failure) != public:
            raise ValueError(failure)
    else:
        destination_module = _source_text(destination, "Runtime typed public export is not literal")
        module_path = f"{module_name}.{destination_module}"
    if (
        not module_path.startswith(module_name + ".")
        or not (source / (module_path.replace(".", "/") + ".py")).is_file()
    ):
        raise ValueError(f"dynamic owner export target missing: {module_path}")
    return ExportBinding(public, module_path)


def _canonical_export_imports(wrapper: ast.Module) -> set[tuple[str, str]]:
    return {
        (alias.name, alias.asname or alias.name)
        for node in wrapper.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "project_runtime_client._lazy_exports"
        for alias in node.names
    }


def _delegated_export_tree(source: Path, wrapper: ast.Module, module_name: str) -> ast.Module:
    """Follow only the exact reviewed source-local export bindings."""
    runtime = module_name == "modules.project_runtime"
    resolver = "_LazyRuntimeExports" if runtime else "_LazyOwnerExports"
    imported = _canonical_export_imports(wrapper)
    required = {(resolver, resolver)}
    if runtime:
        required.add(("_EXPORT_MODULE", "_EXPORT_MODULE"))
    if not required <= imported:
        raise ValueError("Canonical export imports changed")
    binding = "_public_interface" if runtime else "_owner_exports"
    construction = (
        "_LazyRuntimeExports(__name__)"
        if runtime
        else "_LazyOwnerExports(__name__, _OWNER_PUBLIC_EXPORTS, __all__)"
    )
    for name, expression in (
        (binding, construction),
        ("__getattr__", f"{binding}.resolve"),
        ("__dir__", f"{binding}.names"),
    ):
        values = _assigned_values(wrapper, name)
        if len(values) != 1 or ast.unparse(values[0]) != expression:
            raise ValueError("Canonical export delegation changed")
    path = source.parent / "shared/project_runtime_client/_lazy_exports.py"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Canonical export source missing")
    return ast.parse(path.read_text(), filename=str(path))


def _module_exports(
    source: Path, module_name: str, relative: str, variable: str
) -> ModuleExports | None:
    path = source / relative
    if not path.is_file():
        if module_name == "modules.project_runtime":
            raise ValueError("Runtime Project public contract is missing")
        return None
    tree = ast.parse(path.read_text(), filename=str(path))
    canonical = module_name == "modules.project_runtime" and not any(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == variable
        for node in tree.body
    )
    expression_tree = _delegated_export_tree(source, tree, module_name) if canonical else tree
    expression = _export_expression(expression_tree, module_name, variable)
    if expression is None:
        return None
    entries = _source_bindings(expression, f"unbounded public export map in {module_name}")
    if not entries:
        raise ValueError(f"unbounded public export map in {module_name}")
    names = _declared_public_names(tree)
    failure = f"export ABI mismatch in {module_name}"
    if len(names) != 1 or _source_names(names[0], failure) != {name for name, _ in entries}:
        raise ValueError(failure)
    if not canonical and not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__"
        for node in tree.body
    ):
        if module_name != "projects":
            raise ValueError(f"export source missing verified lazy resolver in {module_name}")
        _delegated_export_tree(source, tree, module_name)
    return ModuleExports(
        module_name,
        tuple(_export_binding(source, module_name, public, target) for public, target in entries),
    )


def _lazy_exports(source: Path) -> tuple[ModuleExports, ...]:
    """Resolve only signed-source literal Runtime and A16 Project exports.

    A17 may change these interfaces: an unknown dynamic module must remain
    unresolved rather than inventing an import graph or copying all ORMs.
    """
    result: list[ModuleExports] = []
    specifications = (
        ("modules.project_runtime", "modules/project_runtime/__init__.py", "_EXPORT_MODULE"),
        ("projects", "projects/__init__.py", "_OWNER_PUBLIC_EXPORTS"),
    )
    for module_name, relative, variable in specifications:
        exports = _module_exports(source, module_name, relative, variable)
        if exports is not None:
            result.append(exports)
    return tuple(result)


def _owner_ledger_candidate(owner: str, module: ast.expr) -> OwnerLedgerCandidate:
    return OwnerLedgerCandidate(
        owner, _source_text(module, "unbounded Backend owner-ledger registry")
    )


def _runtime_owner_ledger_candidates(source: Path) -> tuple[OwnerLedgerCandidate, ...]:
    """Report candidates, NOT a resolved per-service DB/runtime dependency."""
    path = source / "common/owner_transactions.py"
    if not path.is_file():
        return ()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_OWNED_LEDGERS"
            and node.value is not None
        ):
            entries = _source_bindings(node.value, "unbounded Backend owner-ledger registry")
            return tuple(_owner_ledger_candidate(owner, module) for owner, module in entries)
    return ()


def _handler_exported(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(name, ast.Name) and name.id == "mcp"
            for target in node.targets
            for name in ast.walk(target)
        )
        for node in tree.body
    )


def _source_handler(source: Path, provider: str, binding: ast.expr) -> ProviderSourceHandler:
    failure = "SVC provider binding differs from reviewed owner modules"
    if not isinstance(binding, ast.Tuple) or len(binding.elts) != 2:
        raise ValueError(failure)
    module_name = f"modules.{provider}.runtime"
    if (
        _source_text(binding.elts[0], failure) != module_name
        or _source_text(binding.elts[1], failure) != "mcp"
    ):
        raise ValueError(failure)
    module_path = source / (module_name.replace(".", "/") + ".py")
    if not module_path.is_file():
        raise ValueError("SVC provider source was removed")
    module_ast = ast.parse(module_path.read_text(), filename=str(module_path))
    if not _handler_exported(module_ast):
        raise ValueError("SVC provider existing handler export disappeared")
    return ProviderSourceHandler(provider, module_name, "mcp")


def _svc_source_handlers(source: Path) -> tuple[ProviderSourceHandler, ...]:
    """Verify both source registries remain packaged, without importing them."""
    catalog = source / "modules/svc/composition.py"
    if not catalog.is_file():
        raise ValueError("SVC selected app needs its owned source selector")
    tree = ast.parse(catalog.read_text(), filename=str(catalog))
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "SVC_SOURCE_HANDLERS"
        and node.value is not None
    ]
    if len(values) != 1:
        raise ValueError("SVC provider source map must be literal and unique")
    entries = _source_bindings(values[0], "SVC GitHub and GitLab private source handlers required")
    if {provider for provider, _ in entries} != {"github", "gitlab"}:
        raise ValueError("SVC GitHub and GitLab private source handlers required")
    return tuple(_source_handler(source, provider, binding) for provider, binding in entries)


class PythonImportGraph:
    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.resolve()
        self.module_files: dict[str, Path] = {}
        self._add_source_root(self.source_root, None)
        self._add_source_root(
            self.source_root.parent / "shared",
            frozenset(
                {"service_runtime", "owner_protocol", "project_runtime_client", "gateway_runtime"}
            ),
        )
        for bounded in _BOUNDED_OWNER_SOURCES:
            self._add_source_root(
                (self.source_root.parent / bounded.source).parent, frozenset({bounded.package})
            )
        self.lazy_exports = {
            module.module_name: {entry.public_name: entry.module_path for entry in module.bindings}
            for module in _lazy_exports(self.source_root)
        }
        self._cache: dict[str, _Imports] = {}

    def _add_source_root(self, directory: Path, allowed: frozenset[str] | None) -> None:
        for path in sorted(directory.rglob("*.py")):
            if any(item in path.parts for item in (".venv", "__pycache__")):
                continue
            if allowed is not None and path.relative_to(directory).parts[0] not in allowed:
                continue
            name = _module_name(path, directory)
            if name in self.module_files:
                raise ValueError(f"ambiguous Python runtime module {name}")
            self.module_files[name] = path

    def _ancestors(self, module: str) -> set[str]:
        parts = module.split(".")
        return {
            ".".join(parts[:i])
            for i in range(1, len(parts) + 1)
            if ".".join(parts[:i]) in self.module_files
        }

    def _visit(self, module: str) -> _Imports:
        if module not in self._cache:
            source = self.module_files[module]
            parsed = ast.parse(source.read_text(), filename=str(source))
            visitor = _Imports(
                module,
                is_package=source.name == "__init__.py",
                lazy_exports=self.lazy_exports,
            )
            visitor.visit(parsed)
            self._cache[module] = visitor
        return self._cache[module]

    @staticmethod
    def _external_import(module: str, external: set[str]) -> None:
        top = module.split(".")[0]
        if top not in sys.stdlib_module_names and top not in sys.builtin_module_names:
            external.add(top)

    def _queue_import(
        self,
        item: str,
        current: str,
        *,
        pending: deque[str],
        selected: set[str],
        dynamic: set[str],
        external: set[str],
    ) -> None:
        if item in self.module_files:
            if item not in selected:
                pending.append(item)
        elif item.split(".")[0] not in (
            {
                "bridge",
                "modules",
                "common",
                "authorization",
                "identity",
                "teams",
                "projects",
                "agents",
                "service_runtime",
                "owner_protocol",
                "project_runtime_client",
                "gateway_runtime",
            }
            | _BOUNDED_IMPORT_ROOTS
        ):
            self._external_import(item, external)
        elif any(m.startswith(item + ".") for m in self.module_files):
            # A namespace import may resolve a child module, not an external root.
            for ancestor in self._ancestors(item):
                if ancestor not in selected:
                    pending.append(ancestor)
        elif item.count(".") == 0:
            dynamic.add(f"{current}:unresolved_first_party_root:{item}")

    def _closure(self, packaged_roots: tuple[str, ...]) -> ImportClosure:
        # D5 executes common.asgi with an exact per-image ASGI_APP string.
        pending = deque((*packaged_roots, "common.asgi"))
        selected: set[str] = set()
        dynamic: set[str] = set()
        external: set[str] = set()
        while pending:
            current = pending.popleft()
            if current in selected:
                continue
            if current not in self.module_files:
                self._external_import(current, external)
                continue
            for ancestor in self._ancestors(current):
                if ancestor not in selected:
                    pending.append(ancestor)
            selected.add(current)
            imports = self._visit(current)
            dynamic.update(imports.dynamic)
            for item in imports.names:
                self._queue_import(
                    item,
                    current,
                    pending=pending,
                    selected=selected,
                    dynamic=dynamic,
                    external=external,
                )
        return ImportClosure(frozenset(selected), frozenset(dynamic), frozenset(external))

    def _packaged_roots(self, name: str, entrypoints: tuple[str, ...]) -> tuple[str, ...]:
        # Bundle every source-owned optional/lazy effect; Gateway retains its
        # exceptional startup-only closure while the legacy registry is retired.
        if name == "gateway":
            return entrypoints
        return tuple(
            sorted(
                module
                for module in self.module_files
                if any(
                    module == prefix or module.startswith(prefix + ".")
                    for prefix in (
                        *_OWNER_PACKAGE[name].split(";"),
                        *(
                            item.package
                            for item in _BOUNDED_OWNER_SOURCES
                            if item.owner == name and item.package != "files_hand"
                        ),
                    )
                )
                or (name == "files" and module == "files_hand.presentation.workspace_ingress")
            )
        )

    def unit(self, name: str) -> Unit:
        if name not in _VALID_RUNTIME:
            raise ValueError(f"unknown owner service {name!r}")
        entrypoints = _SERVICE_ENTRYPOINTS[name]
        closure = self._closure(self._packaged_roots(name, entrypoints))
        paths = tuple(
            sorted(
                self.module_files[n].relative_to(self.source_root.parent).as_posix()
                for n in closure.modules
            )
        )
        owned = tuple(
            x
            for x in paths
            if x.startswith(
                tuple(
                    [
                        "services/" + part.replace(".", "/") + "/"
                        for part in _OWNER_PACKAGE[name].split(";")
                    ]
                    + [item.source + "/" for item in _BOUNDED_OWNER_SOURCES if item.owner == name]
                )
            )
        )
        shared = tuple(
            x
            for x in paths
            if x.startswith(
                (
                    "services/common/",
                    "shared/service_runtime/",
                    "shared/owner_protocol/",
                    "shared/project_runtime_client/",
                    "shared/gateway_runtime/",
                    "services/modules/project_runtime/",
                    "services/modules/workspace_compat/",
                )
            )
        )
        foreign = tuple(
            x
            for x in paths
            if x not in owned and x not in shared and not x.endswith("/modules/__init__.py")
        )
        digest = hashlib.sha256(
            json.dumps(
                [(p, _sha(self.source_root.parent / p)) for p in paths], separators=(",", ":")
            ).encode()
        ).hexdigest()
        return Unit(
            name=name,
            entrypoints=entrypoints,
            source_paths=paths,
            runtime_package_paths=owned,
            shared_source_paths=shared,
            transitive_foreign_source_paths=foreign,
            external_import_roots=tuple(sorted(closure.external_import_roots)),
            dynamic_imports=tuple(sorted(closure.dynamic_imports)),
            hash_sha256=digest,
        )


def _release_unit(repo: Path, name: str, unit: Unit) -> ReleaseUnitManifest:
    return ReleaseUnitManifest(
        entrypoints=list(unit.entrypoints),
        startup_loader="common.asgi",
        expected_asgi_app=f"{unit.entrypoints[0]}:app",
        source_paths=list(unit.source_paths),
        owned_paths=list(unit.runtime_package_paths),
        shared_paths=list(unit.shared_source_paths),
        cross_owner_imports=list(unit.transitive_foreign_source_paths),
        external_import_roots=list(unit.external_import_roots),
        dynamic_imports_to_review=list(unit.dynamic_imports),
        dynamic_owner_ledger_candidates_not_included=(
            {
                entry.owner: entry.module_path
                for entry in _runtime_owner_ledger_candidates(repo / "services")
            }
            if any(
                entry.startswith("common.owner_transactions:nonliteral_dynamic_import")
                for entry in unit.dynamic_imports
            )
            else {}
        ),
        source_content_sha256=unit.hash_sha256,
        public_transport_accepted=False,
        has_accepted_unified_entrypoint=True,
        source_only_transport_pending=name == "svc",
        source_provider_handlers=(
            {
                entry.provider: SourceHandlerManifest(
                    module=entry.module_name, handler=entry.handler
                )
                for entry in _svc_source_handlers(repo / "services")
            }
            if name == "svc"
            else {}
        ),
        owner_alembic_histories=[],
        excluded_unaccepted_source=[
            "services/bridge/legacy_mcp.py",
            "services/bridge/package_graph.py",
        ]
        if name == "gateway"
        else [],
    )


def release_manifest(repo: Path) -> ReleaseManifest:
    graph = PythonImportGraph(repo / "services")
    units = {name: graph.unit(name) for name in _SERVICE_ENTRYPOINTS}
    imports: dict[str, list[str]] = {}
    for name, unit in units.items():
        for path in unit.source_paths:
            imports.setdefault(path, []).append(name)
    return ReleaseManifest(
        schema="runtime-selective-python-source-graph-v1",
        source_tool="services/bridge/package_graph.py",
        source_tool_sha256=_sha(repo / "services/bridge/package_graph.py"),
        evidence="AST_AND_EXPLICIT_LAZY_EXPORTS_ONLY_NO_INSTALLED_DOCKER_OR_C2",
        release_units={name: _release_unit(repo, name, unit) for name, unit in units.items()},
        source_reverse_consumers={k: sorted(v) for k, v in sorted(imports.items())},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = release_manifest(args.repo.resolve())
    rendered = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.write_text(rendered)
    units = manifest["release_units"]
    for name, item in units.items():
        print(
            name,
            "owned",
            len(item["owned_paths"]),
            "shared",
            len(item["shared_paths"]),
            "foreign",
            len(item["cross_owner_imports"]),
            "dynamic",
            len(item["dynamic_imports_to_review"]),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
