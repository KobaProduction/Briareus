"""Source graph ownership, import execution and content receipt invariants."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

import owner_packages
import owner_source_graph as graph


def _write(root: Path, relative: str, content: str = "") -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    for package in ("common", "identity", "authorization", "projects"):
        _write(tmp_path, f"services/{package}/__init__.py")
    names = set(graph._OWNER_ENTRY.values())
    for seeds in owner_packages._OWNER_SOURCE_SURFACES.values():
        names.update(seeds)
    for name in names:
        _write(tmp_path, "services/" + name.replace(".", "/") + ".py", "import common.base\n")
    for _module, relative in graph._SOURCE_CONTROL_PUBLIC:
        _write(tmp_path, relative)
    _write(tmp_path, "services/common/base.py", "import json\nimport pydantic\n")
    registrations = {owner: ("ignored", (entry,)) for owner, entry in graph._OWNER_ENTRY.items()}
    _write(
        tmp_path,
        "services/common/owner_registry.py",
        "_OWNER_MODELS: dict = " + repr(registrations),
    )
    for owner in graph._OWNER_ENTRY:
        _write(tmp_path, f"scripts/alembic_owners/{owner}/env.py")
    for producer in ("owner_source_graph", "owner_packages"):
        _write(tmp_path, f"scripts/{producer}.py", producer)
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\ndependencies = ["pydantic>=2", "asyncpg>=0.31", "uvicorn>=0.35"]\n',
    )
    return tmp_path


def test_graph_hashes_sources_and_partitions_owner_migrations(source_tree: Path) -> None:
    result = graph.source_closure(source_tree)
    assert set(result.units) == {"common", "identity", "access", "platform", "resources"}
    for owner in graph._OWNER_ENTRY:
        assert result.third_party_import_roots[owner] == ["pydantic"]
        migration = f"scripts/alembic_owners/{owner}/env.py"
        assert result.consumer_impact[migration] == [owner]
        assert migration in {item.path for item in result.units[owner]}
    for records in result.units.values():
        for record in records:
            assert (
                record.sha256
                == hashlib.sha256((source_tree / record.path).read_bytes()).hexdigest()
            )
    assert asdict(result)["schema"] == "briareus-owner-source-closure-v1"


def test_packaging_variant_preserves_extra_seed_and_tracks_both_producers(
    source_tree: Path,
) -> None:
    result = owner_packages.source_closure(source_tree)
    assert result.consumer_impact["services/common/private_c2_operation.py"] == ["access"]
    assert result.build_input_paths == [
        "scripts/owner_packages.py",
        "scripts/owner_source_graph.py",
    ]
    _write(source_tree, "scripts/owner_source_graph.py", "changed shared graph implementation")
    assert owner_packages.source_closure(source_tree).producer_sha256 != result.producer_sha256


def test_type_checking_imports_are_excluded_and_parent_initializers_are_loaded(
    source_tree: Path,
) -> None:
    _write(
        source_tree,
        "services/identity/platform_runtime.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n import nonexistent_sdk\n"
        "else:\n import common.base\nraise RuntimeError('never execute source')\n",
    )
    result = graph.source_closure(source_tree)
    assert "nonexistent_sdk" not in result.third_party_import_roots["identity"]
    assert "services/identity/__init__.py" in {item.path for item in result.units["identity"]}


def test_foreign_owner_imports_are_rejected(source_tree: Path) -> None:
    _write(
        source_tree, "services/identity/platform_runtime.py", "import projects.control_runtime\n"
    )
    with pytest.raises(ValueError, match="foreign bounded owner"):
        graph.source_closure(source_tree)


def test_missing_migration_history_is_not_silently_dropped(source_tree: Path) -> None:
    (source_tree / "scripts/alembic_owners/identity/env.py").unlink()
    with pytest.raises(ValueError, match="frozen migration history unavailable"):
        graph.source_closure(source_tree)


def test_ambiguous_native_module_names_are_rejected(source_tree: Path) -> None:
    _write(source_tree, "services/common/base/__init__.py")
    with pytest.raises(ValueError, match="ambiguous Python owner module"):
        graph.source_closure(source_tree)


def test_staging_consumes_named_graph_without_changing_receipt_wire_fields(
    source_tree: Path,
) -> None:
    result = owner_packages.source_closure(source_tree)
    destination = source_tree / "staged"
    owner_packages._stage(source_tree, destination, result)
    assert (destination / "identity/src/common/alembic_owners/identity/env.py").is_file()
    receipt = json.loads((destination / "identity/release_receipt.json").read_text())
    assert receipt["review_state"] == "SOURCE_ONLY_UNPUBLISHED"
    assert all(set(item) == {"path", "sha256"} for item in receipt["source_files"])
    assert "asyncpg>=0.31" in receipt["dependencies"]
    assert receipt["common_dependency"] is not None
    saved_graph = json.loads((destination / "owner_source_graph.json").read_text())
    assert saved_graph["producer_sha256"] == result.producer_sha256
    assert set(saved_graph["units"]) == set(result.units)
    with pytest.raises(FileExistsError, match="immutable"):
        owner_packages._stage(source_tree, destination, result)
