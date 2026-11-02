"""Prove hooks select index content and never silently check partial staging."""

import argparse
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import selection


def repository(path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "-q", str(path)], check=True)  # noqa: S603 -- disposable test repo
    (path / "source.py").write_text("x = 1\n")
    subprocess.run([git, "-C", str(path), "add", "."], check=True)  # noqa: S603 -- disposable test repo


def options() -> argparse.Namespace:
    return argparse.Namespace(staged=True, push=False, all=False, base=None)


def test_staged_paths_are_exact(tmp_path: Path) -> None:
    repository(tmp_path)
    (tmp_path / "unstaged.py").write_text("x = 2\n")
    with patch.object(selection, "ROOT", tmp_path):
        assert selection.selected(options()) == ["source.py"]


def test_partial_staging_is_rejected(tmp_path: Path) -> None:
    repository(tmp_path)
    (tmp_path / "source.py").write_text("x = 2\n")
    with (
        patch.object(selection, "ROOT", tmp_path),
        pytest.raises(ValueError, match="Stage or stash"),
    ):
        selection.selected(options())


def test_empty_inventory_entry_stays_inside_root(tmp_path: Path) -> None:
    with patch.object(selection, "ROOT", tmp_path):
        assert selection.owner("") == tmp_path
        with pytest.raises(ValueError):
            selection.owner("../foreign.py")


def test_nested_dependency_project_retains_its_source_boundary(tmp_path: Path) -> None:
    base = tmp_path / "services/infrastructure/gateway"
    base.mkdir(parents=True)
    (base / "pyproject.toml").touch()
    with patch.object(selection, "ROOT", tmp_path):
        assert selection.source_owner("services/infrastructure/gateway/src/server.py") == base
