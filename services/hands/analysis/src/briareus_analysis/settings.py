from __future__ import annotations

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator


class AnalysisSettings(ProcessSettings):
    backend_url: str = Field(
        "http://ghidra:8000/mcp",
        validation_alias="GHIDRA_URL",
    )
    direct_upload_url: str = Field(
        "http://ghidra-mcp:8081/internal/artifacts/upload",
        validation_alias="GHIDRA_DIRECT_UPLOAD_URL",
    )
    direct_upload_timeout_seconds: float = Field(
        300,
        gt=0,
        le=3600,
        validation_alias="GHIDRA_DIRECT_UPLOAD_TIMEOUT_SECONDS",
    )
    schema_cache_ttl_seconds: float = Field(
        30,
        ge=0,
        le=3600,
        validation_alias="ANALYSIS_SCHEMA_CACHE_TTL_SECONDS",
    )

    @field_validator("backend_url", "direct_upload_url", mode="before")
    @classmethod
    def _strip_backend_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
