from __future__ import annotations

from briareus_server_mount import ServerMountSettings
from pydantic import Field


class FileSettings(ServerMountSettings):
    upload_max_bytes: int = Field(
        8 * 1024 * 1024 * 1024,
        ge=1024 * 1024,
        le=64 * 1024 * 1024 * 1024,
        validation_alias="FILE_UPLOAD_MAX_BYTES",
    )
