"""Project ownership and process settings for the Serena hand."""

from pathlib import Path
from typing import Literal

from briareus_server_mount import ServerMountSettings
from pydantic import BaseModel, ConfigDict, Field


class ProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")
    folder: str = Field(min_length=1)


class ProjectStatus(BaseModel):
    project: ProjectSpec
    state: Literal["stopped", "running", "busy"]
    active_calls: int = 0
    idle_seconds: float = 0


class ProjectRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projects: list[ProjectSpec] = Field(default_factory=list)


class SerenaSettings(ServerMountSettings):
    state_root: Path = Field(Path("/var/lib/briareus/serena"), validation_alias="SERENA_STATE_ROOT")
    command: str = Field("/opt/serena/.venv/bin/serena", validation_alias="SERENA_COMMAND")
    max_processes: int = Field(8, ge=1, le=64, validation_alias="SERENA_MAX_PROCESSES")
    idle_seconds: int = Field(900, ge=30, le=86400, validation_alias="SERENA_IDLE_SECONDS")
    projects: list[ProjectSpec] = Field(default_factory=list, validation_alias="SERENA_PROJECTS")
