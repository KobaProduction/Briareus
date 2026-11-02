"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field

from source_control.providers.gitlab.project_views import (
    GitLabAccountCapabilities as GitLabAccountCapabilities,
)
from source_control.providers.gitlab.project_views import (
    GitLabProfileStatus as GitLabProfileStatus,
)
from source_control.providers.gitlab.project_views import GitLabProjectList as GitLabProjectList
from source_control.providers.gitlab.project_views import (
    GitLabProjectStatus as GitLabProjectStatus,
)
from source_control.providers.gitlab.project_views import ProjectAccess as ProjectAccess
from source_control.providers.gitlab.project_views import ProjectAccesses as ProjectAccesses
from source_control.providers.gitlab.project_views import ProjectScope as ProjectScope
from source_control.providers.gitlab.project_views import (
    PublicGitLabProfile as PublicGitLabProfile,
)
from source_control.providers.gitlab.project_views import PublicPermissions as PublicPermissions
from source_control.providers.gitlab.project_views import TokenPermissions as TokenPermissions
from source_control.providers.gitlab.project_views import UnknownPermissions as UnknownPermissions

from .infrastructure.schemas.identity import AuthenticatedGitLabUser as AuthenticatedGitLabUser
from .infrastructure.schemas.identity import GitLabVersion as GitLabVersion
from .infrastructure.schemas.projects import GitLabProject as GitLabProject
