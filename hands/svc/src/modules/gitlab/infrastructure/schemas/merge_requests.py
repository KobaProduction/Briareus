"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import RootModel as RootModel

from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequest as MergeRequest,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestCreate as MergeRequestCreate,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestDetailsQuery as MergeRequestDetailsQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestQuery as MergeRequestQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestRecords as MergeRequestRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestUpdate as MergeRequestUpdate,
)

from .activity import IssueMilestone as IssueMilestone
from .identity import GitLabUser as GitLabUser
from .pagination import PageQuery as PageQuery
from .pipelines import PipelineSummary as PipelineSummary
from .work_items import GitLabWorkItem as GitLabWorkItem
from .work_items import WorkItemUpdate as WorkItemUpdate


class MergeRequestAccept(BaseModel):
    merge_when_pipeline_succeeds: bool
    sha: str
    should_remove_source_branch: bool
    squash: bool | None = None
    merge_commit_message: str | None = None
    squash_commit_message: str | None = None
