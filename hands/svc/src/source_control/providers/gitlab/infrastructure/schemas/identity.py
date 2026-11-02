"""GitLab-owned identity metadata; never the Briareus identity authority."""

from pydantic import BaseModel


class GitLabUser(BaseModel):
    id: int
    username: str
    name: str
    state: str | None = None
    avatar_url: str | None = None
    web_url: str | None = None


class AuthenticatedGitLabUser(GitLabUser):
    email: str | None = None
    public_email: str | None = None
    commit_email: str | None = None


class GitLabVersion(BaseModel):
    version: str
    revision: str
    enterprise: bool | None = None


class PersonalAccessToken(BaseModel):
    scopes: list[str] | None = None
    active: bool | None = None
    expires_at: str | None = None
