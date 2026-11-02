"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import Field as Field
from pydantic import RootModel as RootModel

from source_control.providers.gitlab.infrastructure.schemas.activity import (
    GitLabIssue as GitLabIssue,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    GitLabNote as GitLabNote,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueCreate as IssueCreate,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueLinks as IssueLinks,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueMilestone as IssueMilestone,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueQuery as IssueQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueRecords as IssueRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueTimeStats as IssueTimeStats,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    IssueUpdate as IssueUpdate,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    JobArtifact as JobArtifact,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    JobArtifactFile as JobArtifactFile,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import JobRunner as JobRunner
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    NoteCreate as NoteCreate,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    PipelineJob as PipelineJob,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    PipelineJobQuery as PipelineJobQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    PipelineJobRecords as PipelineJobRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    PipelineQuery as PipelineQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    PipelineRecords as PipelineRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.activity import (
    TaskCompletion as TaskCompletion,
)

from .identity import GitLabUser as GitLabUser
from .pagination import PageQuery as PageQuery
from .pipelines import PipelineSummary as PipelineSummary
from .repository import GitLabCommit as GitLabCommit
from .work_items import GitLabWorkItem as GitLabWorkItem
from .work_items import WorkItemUpdate as WorkItemUpdate
