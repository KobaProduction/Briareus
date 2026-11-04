from __future__ import annotations

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator


class GhidraSettings(ProcessSettings):
    backend_url: str = Field(
        min_length=1,
        validation_alias="GHIDRA_MCP_URL",
    )

    @field_validator("backend_url", mode="before")
    @classmethod
    def _strip_backend_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
