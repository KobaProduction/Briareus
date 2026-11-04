from __future__ import annotations

from typing import Annotated

from briareus_environment_models import ProcessSettings
from briareus_environment_parsing import parse_csv_tuple
from briareus_http_surface import HttpSurfaceSettings
from pydantic import Field, field_validator
from pydantic_settings import NoDecode

_DEFAULT_PRIVATE_HOSTS = (
    "localhost:*",
    "127.0.0.1:*",
    "[::1]:*",
    "github:*",
    "gitlab:*",
    "server:*",
    "web:*",
    "analysis:*",
    "ghidra:*",
    "observability:*",
    "auth:*",
)


_DEFAULT_PRIVATE_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)


class PrivateRuntimeSettings(ProcessSettings):
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_HOSTS,
        validation_alias="PRIVATE_MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_ORIGINS,
        validation_alias="PRIVATE_MCP_ALLOWED_ORIGINS",
    )

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return parse_csv_tuple(value)

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )
