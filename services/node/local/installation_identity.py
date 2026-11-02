"""The existing private local installation marker shared by Node delivery CLIs."""

from pydantic import UUID4, BaseModel, ConfigDict


class InstallationIdentity(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    node_uuid: UUID4
    registry_host: str
