from __future__ import annotations

from collections.abc import Callable as Callable

from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from source_control.providers.gitlab.issue_tools import (
    register_gitlab_issue_tools as register_gitlab_issue_tools,
)

from .activity_views import IssueList as IssueList
from .activity_views import IssueNote as IssueNote
from .activity_views import IssueResponse as IssueResponse
from .gitlab_client import GitLabClient as GitLabClient
