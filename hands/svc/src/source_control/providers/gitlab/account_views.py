"""Credential-free GitLab account catalog and capability hints."""

from pydantic import BaseModel

from source_control.account_views import SourceAccountView


class GitLabAccountView(SourceAccountView):
    pass


class GitLabAccountList(BaseModel):
    accounts: list[GitLabAccountView]
    count: int
