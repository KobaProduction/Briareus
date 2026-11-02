"""Controller-issued public routing evidence shared with its private worker."""

from typing import Literal
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field, field_validator

from .control import canonical


class PublicRoutingFacts(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    subnet: str
    gateway: str
    dns: list[Literal["127.0.0.11"]] = Field(min_length=1, max_length=1)


class PublicNetworkAttestation(PublicRoutingFacts):
    profile: Literal["public"]
    node_uuid: UUID4
    project_uuid: UUID4
    placement_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    bridge: str = Field(pattern=r"^br-[a-f0-9]{12}$")
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ready: Literal[True]

    @field_validator("node_uuid", "project_uuid", "placement_uuid", mode="before")
    @classmethod
    def canonical_uuid(cls, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            parsed = UUID(value)
            if str(parsed) == value:
                return parsed
        raise ValueError("Canonical placement UUID required")

    @field_validator("ready", mode="before")
    @classmethod
    def accepted(cls, value: object) -> Literal[True]:
        if value is not True:
            raise ValueError("Controller-applied network policy required")
        return True

    def require_placement(
        self, node_uuid: UUID, project_uuid: UUID, placement_uuid: UUID, fingerprint: str
    ) -> None:
        if (
            self.node_uuid != node_uuid
            or self.project_uuid != project_uuid
            or self.placement_uuid != placement_uuid
            or self.fingerprint != fingerprint
        ):
            raise ValueError("Network attestation differs from accepted placement")

    def canonical_bytes(self) -> bytes:
        return canonical(self.model_dump(mode="json"))
