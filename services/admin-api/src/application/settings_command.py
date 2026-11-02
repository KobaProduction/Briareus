"""Validated command for legacy runtime settings updates."""

from pydantic import BaseModel, ConfigDict, Field


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field("", max_length=64)
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = Field(30, ge=1, le=3650)
    logging_max_records: int = Field(10_000, ge=100, le=1_000_000)
    maintenance_interval_minutes: int = Field(60, ge=1, le=1440)
    terminal_max_exec_timeout_seconds: int = Field(21_600, ge=1, le=86_400)
    terminal_max_job_runtime_seconds: int = Field(43_200, ge=1, le=604_800)
    mcp_call_timeout_seconds: int = Field(5, ge=1, le=300)
    browser_external_enabled: bool = False
    browser_external_mcp_url: str = Field("", max_length=2048)
    browser_call_timeout_seconds: int = Field(300, ge=1, le=1800)
    browser_auto_disconnect_enabled: bool = False
    browser_idle_timeout_seconds: int = Field(300, ge=30, le=86_400)
    browser_profile_dir_name: str = Field("Default", min_length=1, max_length=128)
    browser_extension_token: str = Field("", max_length=4096)
    browser_clear_extension_token: bool = False
    github_local_first_guidance: bool = True
    github_local_git_transport_enabled: bool = True
    github_remote_source_mutations_enabled: bool = False
    gitlab_local_first_guidance: bool = True
    gitlab_local_git_transport_enabled: bool = True
    gitlab_remote_source_mutations_enabled: bool = False
    reverse_idle_timeout_seconds: float = Field(900.0, ge=0, le=86_400)
