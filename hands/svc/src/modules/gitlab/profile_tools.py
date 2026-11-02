from __future__ import annotations

from collections.abc import Callable as Callable

from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from source_control.providers.gitlab.profile_tools import (
    register_gitlab_profile_tools as register_gitlab_profile_tools,
)

from .account_views import GitLabAccountList as GitLabAccountList
from .gitlab_client import GitLabClient as GitLabClient
from .project_views import GitLabAccountCapabilities as GitLabAccountCapabilities
from .project_views import GitLabProfileStatus as GitLabProfileStatus
from .project_views import GitLabProjectList as GitLabProjectList
from .project_views import GitLabProjectStatus as GitLabProjectStatus
