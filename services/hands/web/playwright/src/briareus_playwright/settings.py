from __future__ import annotations

from pathlib import Path

from briareus_environment_models import ProcessSettings
from pydantic import Field, field_validator


class BrowserSettings(ProcessSettings):
    cdp_url: str = Field("http://chromium:9222", validation_alias="BROWSER_CDP_URL")
    control_url: str = Field("http://chromium:9001/RPC2", validation_alias="BROWSER_CONTROL_URL")
    control_token: str = Field("", validation_alias="BROWSER_CONTROL_TOKEN", repr=False)
    profile_dir: Path = Field(
        Path("/browser/profile"),
        validation_alias="BROWSER_PROFILE_PATH",
    )
    executable_path: str = Field(
        "/usr/bin/chromium",
        validation_alias="BROWSER_EXECUTABLE_PATH",
    )
    timezone: str = Field("UTC", validation_alias="TZ")
    timeout_ms: int = Field(30_000, ge=1_000, le=120_000, validation_alias="BROWSER_TIMEOUT_MS")
    max_snapshot_text_chars: int = Field(
        30_000,
        ge=1_000,
        le=200_000,
        validation_alias="BROWSER_MAX_SNAPSHOT_TEXT_CHARS",
    )
    max_snapshot_elements: int = Field(
        250,
        ge=10,
        le=2_000,
        validation_alias="BROWSER_MAX_SNAPSHOT_ELEMENTS",
    )

    @field_validator("profile_dir")
    @classmethod
    def _absolute_profile_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("browser paths must be absolute")
        return value.resolve(strict=False)

    @field_validator("timezone", mode="before")
    @classmethod
    def _normalize_browser_timezone(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or "UTC"
        return value

    @field_validator("executable_path", mode="before")
    @classmethod
    def _strip_executable_path(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
