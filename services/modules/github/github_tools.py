from __future__ import annotations

from collections.abc import Callable as Callable
from typing import TYPE_CHECKING as TYPE_CHECKING

from source_control.providers.github.github_tools import (
    register_github_workflow_tools as register_github_workflow_tools,
)

from .github_actions import GitHubActionsClient as GitHubActionsClient
