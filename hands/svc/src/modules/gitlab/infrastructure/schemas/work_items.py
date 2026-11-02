"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import Field as Field

from source_control.providers.gitlab.infrastructure.schemas.work_items import (
    GitLabWorkItem as GitLabWorkItem,
)
from source_control.providers.gitlab.infrastructure.schemas.work_items import (
    WorkItemUpdate as WorkItemUpdate,
)

from .identity import GitLabUser as GitLabUser
