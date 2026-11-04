from __future__ import annotations

from pathlib import Path

from briareus_server_mount import ServerMountSettings
from pydantic import Field, field_validator


class TerminalSettings(ServerMountSettings):
    home: Path = Field(
        Path("/home/agent"),
        validation_alias="TERMINAL_HOME",
    )
    shell: str = Field("/bin/bash", validation_alias="TERMINAL_SHELL")
    path: str = Field(
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        validation_alias="TERMINAL_PATH",
    )
    lang: str = Field("C.UTF-8", validation_alias="TERMINAL_LANG")
    term: str = Field("xterm-256color", validation_alias="TERMINAL_TERM")
    max_exec_output_bytes: int = Field(
        2 * 1024 * 1024,
        ge=1024,
        le=64 * 1024 * 1024,
        validation_alias="TERMINAL_MAX_EXEC_OUTPUT_BYTES",
    )
    max_job_read_bytes: int = Field(
        1024 * 1024,
        ge=1024,
        le=16 * 1024 * 1024,
        validation_alias="TERMINAL_MAX_JOB_READ_BYTES",
    )
    max_job_log_bytes: int = Field(
        256 * 1024 * 1024,
        ge=1024 * 1024,
        le=8 * 1024 * 1024 * 1024,
        validation_alias="TERMINAL_MAX_JOB_LOG_BYTES",
    )

    @field_validator("home")
    @classmethod
    def _absolute_terminal_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("terminal paths must be absolute")
        return value.resolve(strict=False)

    @field_validator("shell", "path", "lang", "term", mode="before")
    @classmethod
    def _strip_terminal_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
