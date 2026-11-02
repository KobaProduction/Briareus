"""Small persisted node facts that are distinct from execution configuration."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ArtifactConfigurationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["approved_node_adapter"]


class ArtifactStorageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: StrictBool
    purpose: str
    retention: Literal["persistent"] = "persistent"


class PlacementCreationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intent_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
