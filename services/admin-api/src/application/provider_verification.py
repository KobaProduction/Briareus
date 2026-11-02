"""Provider verification metadata; credentials never enter the result contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from common.provider_identity import CoolifyTeamMetadata, SigNozReply, SigNozServiceAccount


class VerifiedProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: bool = True
    account: str


class GitHubVerification(VerifiedProvider):
    provider: Literal["github"] = "github"
    auth_type: str
    app_id: str | None
    login: str | None = None
    slug: str | None = None
    name: str | None = None


class GitLabVerification(VerifiedProvider):
    provider: Literal["gitlab"] = "gitlab"
    user_id: int
    username: str | None = None
    name: str | None = None
    base_url: str


class SigNozVerification(VerifiedProvider):
    provider: Literal["signoz"] = "signoz"
    base_url: str
    service_account: SigNozReply[SigNozServiceAccount]


class CoolifyVerification(VerifiedProvider):
    provider: Literal["coolify"] = "coolify"
    base_url: str
    team: CoolifyTeamMetadata


type ConnectionVerification = (
    GitHubVerification | GitLabVerification | SigNozVerification | CoolifyVerification
)
