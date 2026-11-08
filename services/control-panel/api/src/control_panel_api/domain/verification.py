from __future__ import annotations

from typing import Literal

from briareus_json_values import JsonObject, ProviderModel, StrictModel


class GitHubIdentity(ProviderModel):
    login: str | None = None
    slug: str | None = None
    name: str | None = None


class GitLabIdentity(ProviderModel):
    id: int | None = None
    username: str | None = None
    name: str | None = None


class GitHubVerification(StrictModel):
    ok: Literal[True] = True
    provider: Literal["github"] = "github"
    account: str
    auth_type: str
    app_id: str | None
    login: str | None
    slug: str | None
    name: str | None


class GitLabVerification(StrictModel):
    ok: Literal[True] = True
    provider: Literal["gitlab"] = "gitlab"
    account: str
    user_id: int | None
    username: str | None
    name: str | None
    base_url: str


class SigNozVerification(StrictModel):
    ok: Literal[True] = True
    provider: Literal["signoz"] = "signoz"
    account: str
    base_url: str
    service_account: JsonObject


class CoolifyVerification(StrictModel):
    ok: Literal[True] = True
    provider: Literal["coolify"] = "coolify"
    account: str
    base_url: str
    team: JsonObject


type ConnectionVerification = (
    GitHubVerification | GitLabVerification | SigNozVerification | CoolifyVerification
)
