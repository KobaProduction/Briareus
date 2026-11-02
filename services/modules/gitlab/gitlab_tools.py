from __future__ import annotations

from typing import TYPE_CHECKING as TYPE_CHECKING

from source_control.providers.gitlab.gitlab_tools import (
    register_gitlab_tools as register_gitlab_tools,
)

from .tool_context import GitLabRuntimeContext as GitLabRuntimeContext
