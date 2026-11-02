from __future__ import annotations

from collections.abc import Callable as Callable

from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from source_control.providers.gitlab.pipeline_tools import (
    register_gitlab_pipeline_tools as register_gitlab_pipeline_tools,
)

from .activity_views import JobTrace as JobTrace
from .activity_views import PipelineJobs as PipelineJobs
from .activity_views import PipelineList as PipelineList
from .activity_views import PipelineResult as PipelineResult
from .gitlab_client import GitLabClient as GitLabClient
