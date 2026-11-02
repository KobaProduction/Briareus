from __future__ import annotations

import threading as threading

from common.admin_api_client import AdminApiClient as AdminApiClient
from common.settings import GitLabSettings as GitLabSettings
from source_control.providers.gitlab.tool_context import (
    GitLabRuntimeContext as _SharedGitLabRuntimeContext,
)

from .account_views import GitLabAccountList as GitLabAccountList
from .account_views import GitLabAccountView as GitLabAccountView
from .gitlab_client import GitLabClient as GitLabClient
from .models import GitLabProfile as GitLabProfile
from .project_views import GitLabAccountCapabilities as GitLabAccountCapabilities


class GitLabRuntimeContext(_SharedGitLabRuntimeContext[GitLabClient, AdminApiClient]):
    client_type = GitLabClient
