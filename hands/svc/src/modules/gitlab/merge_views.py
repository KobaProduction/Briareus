"""Field-exact GitLab MCP views; upstream documents stay at this provider boundary."""

from typing import Literal

from modules.github.application.merge import LocalCleanupFailed, LocalWorktreeCleanup
from source_control.providers.gitlab.merge_receipts import MergeRequestResult


class MergeRequestMerged(MergeRequestResult):
    source_branch_action: Literal["delete", "keep"]
    local_cleanup: LocalWorktreeCleanup | LocalCleanupFailed | None
