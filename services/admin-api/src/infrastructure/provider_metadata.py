"""Provider identity replies consumed by the account verification adapter."""

from pydantic import BaseModel, ConfigDict, Field


class IdentityMetadata(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    name: str | None = None


class GitHubUserMetadata(IdentityMetadata):
    login: str = Field(min_length=1)


class GitHubAppMetadata(IdentityMetadata):
    slug: str = Field(min_length=1)


class GitLabUserMetadata(IdentityMetadata):
    id: int = Field(strict=True)
    username: str = Field(min_length=1)
