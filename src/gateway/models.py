from __future__ import annotations

from typing import Literal

from common.models import StrictModel


class GatewayPing(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["bri"] = "bri"
    version: str
    time: str


class GatewayBuildInfo(StrictModel):
    service: Literal["bri"] = "bri"
    version: str
    commit: str
    built_at: str
    started_at: str
    python: str


class GatewayCapabilities(StrictModel):
    backends: list[str]
    public_surfaces: list[str]
    features: list[str]
    status: Literal["active"] = "active"
