"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel

from common.account_contracts import AccountPublic as AccountPublic
from source_control.providers.gitlab.account_views import GitLabAccountList as GitLabAccountList
from source_control.providers.gitlab.account_views import GitLabAccountView as GitLabAccountView
