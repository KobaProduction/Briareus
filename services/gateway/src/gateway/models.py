from __future__ import annotations

from typing import Literal

from briareus_json_values import StrictModel


class GatewayPing(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["briareus"] = "briareus"
    version: str
    time: str
    node_hostname: str
    node_id: str


class GatewayBuildInfo(StrictModel):
    service: Literal["briareus"] = "briareus"
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


class GatewayHealth(StrictModel):
    status: Literal["ok"] = "ok"
    node: str
    commit: str


class RouteNotFound(StrictModel):
    code: Literal["not_found"] = "not_found"


class ServiceUnavailable(StrictModel):
    code: Literal["service_unavailable"] = "service_unavailable"
    service: str
