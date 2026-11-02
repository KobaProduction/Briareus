"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import Field as Field
from pydantic import RootModel as RootModel

from source_control.providers.gitlab.infrastructure.schemas.projects import (
    GitLabNamespace as GitLabNamespace,
)
from source_control.providers.gitlab.infrastructure.schemas.projects import (
    GitLabProject as GitLabProject,
)
from source_control.providers.gitlab.infrastructure.schemas.projects import (
    ProjectMembership as ProjectMembership,
)
from source_control.providers.gitlab.infrastructure.schemas.projects import (
    ProjectPermissions as ProjectPermissions,
)
from source_control.providers.gitlab.infrastructure.schemas.projects import (
    ProjectQuery as ProjectQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.projects import (
    ProjectRecords as ProjectRecords,
)

from .pagination import PageQuery as PageQuery
