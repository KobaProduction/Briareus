"""Behavior checks for domain/application dependency direction and owner naming."""

from pathlib import Path
from unittest.mock import patch

import architecture
import selection


def write_source(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_domain_and_application_import_direction(tmp_path: Path) -> None:
    cases = [
        ("domain/policy.py", "from sqlalchemy import select", True),
        ("domain/user.py", "from dataclasses import dataclass", False),
        ("domain/policy.py", "from ..application.commands import Command", True),
        ("application/run.py", "from ..infrastructure.repo import Repository", True),
        ("application/run.py", "from .._persistence import Repository", True),
        ("domain/policy.py", "from .._application.commands import Command", True),
        ("application/run.py", "from ..domain.policy import Policy", False),
        ("application/commands.py", "from pydantic import BaseModel", False),
    ]
    base = "services/demo"
    write_source(tmp_path, base + "/pyproject.toml", "[project]\nname='demo'")
    with patch.object(architecture, "ROOT", tmp_path), patch("selection.ROOT", tmp_path):
        for suffix, code, blocked in cases:
            path = base + "/src/demo/" + suffix
            write_source(tmp_path, path, code)
            assert bool(architecture.file_findings(path)) is blocked


def test_infrastructure_hand_name_is_not_an_inner_layer(tmp_path: Path) -> None:
    base = "hands/infrastructure"
    path = base + "/src/infrastructure_hand/server.py"
    write_source(tmp_path, base + "/pyproject.toml", "[project]\nname='infra'")
    write_source(tmp_path, path, "import httpx")
    with patch.object(architecture, "ROOT", tmp_path), patch("selection.ROOT", tmp_path):
        assert architecture.layer_for(path) is None
        assert architecture.file_findings(path) == []


def test_no_pyproject_admin_relative_import_uses_logical_source_root(tmp_path: Path) -> None:
    path = "services/admin-api/src/admin/application/run.py"
    write_source(tmp_path, "pyproject.toml", "[project]\nname='root'")
    write_source(tmp_path, path, "from ..infrastructure.repo import Repository")
    with patch.object(architecture, "ROOT", tmp_path), patch.object(selection, "ROOT", tmp_path):
        assert selection.owner(path) == tmp_path
        assert architecture.package_for(path) == ("admin", "application")
        findings = architecture.file_findings(path)
        assert len(findings) == 1
        assert findings[0].message == (
            "application depends outward on admin.infrastructure.repo; define an inward port/DTO."
        )
