"""Policies for changing only Watch Paths on one pre-approved Development app."""

from __future__ import annotations

import re
from dataclasses import dataclass

COOLIFY_ORIGIN = "https://coolify.koba-nexus.ru"
PROJECT_UUID = "3xshlpoghb9wcyhjgktlqzzp"
ENVIRONMENT_UUID = "naibrku1omovvmw5o0bcnp5c"
REPOSITORY = "KobaProduction/briareus"


class SyncError(RuntimeError):
    """A safe diagnostic that never includes remote response values."""


@dataclass(frozen=True)
class ApplicationIdentity:
    slug: str
    uuid: str


@dataclass(frozen=True)
class ApprovedWatchTarget:
    identity: ApplicationIdentity
    base_directory: str
    compose_location: str
    branch: str
    watch_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]{24}", self.identity.uuid):
            raise SyncError("invalid approved Application UUID")
        if self.branch != "main":
            raise SyncError("Watch Paths sync requires the active Development branch main")
        if not self.watch_paths or len(self.watch_paths) > 100:
            raise SyncError("watch paths missing or excessive")
        if len(set(self.watch_paths)) != len(self.watch_paths):
            raise SyncError("duplicate watch path")
        if "services/external/**" not in self.watch_paths:
            raise SyncError("shared External directory watch is required")
        for path in self.watch_paths:
            if (
                not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./*?-]*", path)
                or len(path) > 255
                or ".." in path.split("/")
            ):
                raise SyncError("invalid watch path value")

    @property
    def watch_value(self) -> str:
        return "\n".join(self.watch_paths)


@dataclass(frozen=True)
class SavedWatchMetadata:
    uuid: str
    repository: str
    branch: str
    base_directory: str
    compose_location: str
    build_pack: str
    watch_paths: str

    def require_target(self, target: ApprovedWatchTarget) -> None:
        if self.uuid != target.identity.uuid:
            raise SyncError("Coolify response does not match the approved Application UUID")
        allowed_repositories = {
            REPOSITORY.casefold(),
            f"https://github.com/{REPOSITORY}".casefold(),
            f"https://github.com/{REPOSITORY}.git".casefold(),
        }
        if self.repository.casefold() not in allowed_repositories:
            raise SyncError("unexpected canonical Git repository; refusing update")
        if self.branch != target.branch:
            raise SyncError("unexpected published Git branch; refusing update")
        if self.base_directory != target.base_directory:
            raise SyncError("unexpected Base directory; refusing update")
        if self.compose_location != target.compose_location:
            raise SyncError("unexpected Compose location; refusing update")
        if self.build_pack != "dockercompose":
            raise SyncError("target is not a Git-backed Docker Compose Application")
