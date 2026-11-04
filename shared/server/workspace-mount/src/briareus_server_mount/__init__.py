"""One mounted filesystem and root-relative project paths for server consumers."""

from __future__ import annotations

import re
from pathlib import Path

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ServerMountError(ValueError):
    """A path would escape the configured server mount."""


def resolve_mount_root(value: Path) -> Path:
    if not value.is_absolute():
        raise ServerMountError("SERVER_MOUNT_PATH must be absolute")
    return value.resolve(strict=False)


def resolve_mount_path(root: Path, value: str, *, allow_root: bool = False) -> Path:
    """Resolve a mount-relative path, following symlinks before checking containment."""
    root = resolve_mount_root(root)
    raw = value.strip().replace("\\", "/").lstrip("/")
    if not raw and not allow_root:
        raise ServerMountError("path is required")
    target = (root / raw).resolve(strict=False)
    if not target.is_relative_to(root):
        raise ServerMountError("path escapes server mount")
    if target == root and not allow_root:
        raise ServerMountError("operation on server mount root is not allowed")
    return target


def projects_path(root: Path) -> Path:
    return resolve_mount_path(root, "projects")


def project_identifier(project_id: str) -> str:
    identifier = project_id.strip()
    if not _PROJECT_ID.fullmatch(identifier) or identifier in {".", ".."}:
        raise ServerMountError(
            "workspace_id must start with an alphanumeric character and contain only "
            "letters, digits, dot, underscore or hyphen"
        )
    return identifier


def project_path(root: Path, project_id: str) -> Path:
    return resolve_mount_path(projects_path(root), project_identifier(project_id))


class ServerMountSettings(ProcessSettings):
    workspace_root: Path = Field(Path("/workspace"), validation_alias="SERVER_MOUNT_PATH")

    @field_validator("workspace_root")
    @classmethod
    def _absolute_mount(cls, value: Path) -> Path:
        return resolve_mount_root(value)


def configured_mount_root() -> Path:
    return ServerMountSettings().workspace_root
