"""Compatibility exports for the shared GitLab technical implementation."""

from source_control.providers.gitlab.projects import GitLabProjectClient as GitLabProjectClient
from source_control.providers.gitlab.projects import _access_level_name as _access_level_name
from source_control.providers.gitlab.projects import _project_access as _project_access

from .api import GitLabApiClient as GitLabApiClient
from .errors import GitLabError as GitLabError
from .infrastructure.schemas.identity import AuthenticatedGitLabUser as AuthenticatedGitLabUser
from .infrastructure.schemas.identity import GitLabVersion as GitLabVersion
from .infrastructure.schemas.identity import PersonalAccessToken as PersonalAccessToken
from .infrastructure.schemas.projects import GitLabProject as GitLabProject
from .infrastructure.schemas.projects import ProjectMembership as ProjectMembership
from .infrastructure.schemas.projects import ProjectQuery as ProjectQuery
from .infrastructure.schemas.projects import ProjectRecords as ProjectRecords
from .project_views import GitLabAccountCapabilities as GitLabAccountCapabilities
from .project_views import GitLabProfileStatus as GitLabProfileStatus
from .project_views import GitLabProjectList as GitLabProjectList
from .project_views import GitLabProjectStatus as GitLabProjectStatus
from .project_views import ProjectAccess as ProjectAccess
from .project_views import ProjectAccesses as ProjectAccesses
from .project_views import ProjectScope as ProjectScope
from .project_views import PublicPermissions as PublicPermissions
from .project_views import TokenPermissions as TokenPermissions
from .project_views import UnknownPermissions as UnknownPermissions
