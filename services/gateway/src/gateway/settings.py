from __future__ import annotations

from typing import Annotated

from briareus_environment_models import ProcessSettings
from briareus_environment_parsing import parse_csv_tuple
from briareus_http_surface import HttpSurfaceSettings
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import NoDecode

_DEFAULT_PUBLIC_HOSTS = ("localhost:*", "127.0.0.1:*", "[::1]:*")


_DEFAULT_PUBLIC_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)


class GatewaySettings(ProcessSettings):
    github_url: str = Field("http://github:8000/mcp", validation_alias="GITHUB_URL")
    gitlab_url: str = Field("http://gitlab:8000/mcp", validation_alias="GITLAB_URL")
    server_url: str = Field("http://server:8000/mcp", validation_alias="SERVER_URL")
    web_url: str = Field("http://web:8000/mcp", validation_alias="WEB_URL")
    analysis_url: str = Field(
        "http://analysis:8000/mcp",
        validation_alias="ANALYSIS_URL",
    )
    ghidra_url: str = Field(
        "http://ghidra:8000/mcp",
        validation_alias="GHIDRA_URL",
    )
    observability_url: str = Field(
        "http://observability:8000/mcp",
        validation_alias="OBSERVABILITY_URL",
    )
    build_sha: str = Field(
        "unknown",
        validation_alias=AliasChoices("BUILD_SHA", "SOURCE_COMMIT"),
    )
    build_time: str = Field("unknown", validation_alias="BUILD_TIME")
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PUBLIC_HOSTS,
        validation_alias="MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PUBLIC_ORIGINS,
        validation_alias="MCP_ALLOWED_ORIGINS",
    )

    @field_validator(
        "github_url",
        "gitlab_url",
        "server_url",
        "web_url",
        "analysis_url",
        "ghidra_url",
        "observability_url",
        "build_sha",
        "build_time",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return parse_csv_tuple(value)

    @property
    def backends(self) -> dict[str, str]:
        return {
            "github": self.github_url or "http://github:8000/mcp",
            "gitlab": self.gitlab_url or "http://gitlab:8000/mcp",
            "server": self.server_url or "http://server:8000/mcp",
            "web": self.web_url or "http://web:8000/mcp",
            "analysis": self.analysis_url or "http://analysis:8000/mcp",
            "ghidra": self.ghidra_url or "http://ghidra:8000/mcp",
            "observability": self.observability_url or "http://observability:8000/mcp",
        }

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )
