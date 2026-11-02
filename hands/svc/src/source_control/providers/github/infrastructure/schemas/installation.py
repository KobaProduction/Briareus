"""Installation metadata and credential replies, validated at the GitHub boundary."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel, SecretStr

from .permissions import AppPermissions


class InstallationReference(BaseModel):
    id: int = Field(gt=0)


class InstallationReferences(RootModel[list[InstallationReference]]):
    pass


class InstallationTokenReply(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    token: SecretStr = Field(min_length=1, repr=False)
    expires_at: AwareDatetime = Field(strict=True)

    permissions: AppPermissions = Field(default_factory=AppPermissions)
