"""Account and App identity documents at the GitHub HTTP boundary."""

from pydantic import BaseModel, Field

from source_control.providers.github.history_views import ActorSource

from .permissions import AppPermissions


class UserRecord(ActorSource):
    login: str = Field(min_length=1)
    id: int = Field(gt=0)
    name: str | None = None
    email: str | None = None


class AppRecord(BaseModel):
    slug: str = Field(min_length=1)
    name: str = ""
    permissions: AppPermissions = Field(default_factory=AppPermissions)
