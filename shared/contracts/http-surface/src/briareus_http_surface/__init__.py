from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HttpSurfaceSettings(BaseModel):
    """Allowed request hosts and browser origins for one HTTP surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
