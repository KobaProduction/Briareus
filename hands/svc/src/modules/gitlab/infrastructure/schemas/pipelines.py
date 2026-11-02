"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel

from source_control.providers.gitlab.infrastructure.schemas.pipelines import (
    PipelineDetails as PipelineDetails,
)
from source_control.providers.gitlab.infrastructure.schemas.pipelines import (
    PipelineSummary as PipelineSummary,
)

from .identity import GitLabUser as GitLabUser
