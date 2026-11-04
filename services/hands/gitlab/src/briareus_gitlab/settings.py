from __future__ import annotations

from typing import Annotated

from briareus_environment_parsing import parse_csv_frozenset
from briareus_server_mount import ServerMountSettings
from pydantic import Field, field_validator
from pydantic_settings import NoDecode


class GitLabSettings(ServerMountSettings):
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset(),
        validation_alias="GITLAB_PROTECTED_BRANCHES",
    )
    registry_cache_ttl_seconds: float = Field(
        60,
        ge=0,
        le=3600,
        validation_alias="GITLAB_REGISTRY_CACHE_TTL_SECONDS",
    )

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _parse_branches(cls, value: object) -> object:
        return parse_csv_frozenset(value)
