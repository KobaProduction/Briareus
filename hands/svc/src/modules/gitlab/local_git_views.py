"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel

from service_runtime.checkout_contracts import RepositoryCheckout as RepositoryCheckout
from source_control.providers.gitlab.local_git_views import GitLabCheckout as GitLabCheckout
from source_control.providers.gitlab.local_git_views import (
    GitLabGitAuthorization as GitLabGitAuthorization,
)
from source_control.providers.gitlab.local_git_views import GitLabGitPush as GitLabGitPush
