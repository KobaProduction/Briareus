"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel

from source_control.providers.gitlab.infrastructure.schemas.identity import (
    AuthenticatedGitLabUser as AuthenticatedGitLabUser,
)
from source_control.providers.gitlab.infrastructure.schemas.identity import (
    GitLabUser as GitLabUser,
)
from source_control.providers.gitlab.infrastructure.schemas.identity import (
    GitLabVersion as GitLabVersion,
)
from source_control.providers.gitlab.infrastructure.schemas.identity import (
    PersonalAccessToken as PersonalAccessToken,
)
