from datetime import datetime

from briareus_service_catalog import ServiceDefinition
from pydantic import BaseModel, ConfigDict


class ServiceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    service: ServiceDefinition
    environment: str
    ready: bool = True


class DiscoveredService(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    group: str
    connected: bool
    mcp_path: str


class DiscoverySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    services: tuple[DiscoveredService, ...]
    checked_at: datetime
