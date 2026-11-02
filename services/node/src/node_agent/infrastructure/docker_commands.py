"""Supported private daemon commands; JSON serialization belongs to the HTTP adapter."""

from pydantic import BaseModel, ConfigDict, Field

from .container_models import DockerPayload


class IpamSubnet(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)
    subnet: str = Field(default="", alias="Subnet")
    gateway: str | None = Field(default=None, alias="Gateway")


class NetworkIpam(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)
    driver: str | None = Field(default=None, alias="Driver")
    configs: list[IpamSubnet] | None = Field(default=None, alias="Config")


class NetworkCreate(DockerPayload):
    name: str = Field(alias="Name")
    driver: str = Field(alias="Driver")
    internal: bool = Field(alias="Internal")
    ipv6: bool = Field(alias="EnableIPv6")
    labels: dict[str, str] = Field(alias="Labels")
    ipam: NetworkIpam = Field(alias="IPAM")


class NetworkConnect(DockerPayload):
    container: str = Field(alias="Container")


class VolumeCreate(DockerPayload):
    name: str = Field(alias="Name")
    driver: str = Field(alias="Driver")
    labels: dict[str, str] = Field(alias="Labels")
