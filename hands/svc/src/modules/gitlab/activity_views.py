"""Compatibility exports for the shared GitLab technical implementation."""

from source_control.providers.gitlab.activity_views import IssueList as IssueList
from source_control.providers.gitlab.activity_views import IssueNote as IssueNote
from source_control.providers.gitlab.activity_views import IssueResponse as IssueResponse
from source_control.providers.gitlab.activity_views import JobTrace as JobTrace
from source_control.providers.gitlab.activity_views import PipelineJobs as PipelineJobs
from source_control.providers.gitlab.activity_views import PipelineList as PipelineList
from source_control.providers.gitlab.activity_views import PipelineResult as PipelineResult

from .infrastructure.schemas.activity import GitLabIssue as GitLabIssue
from .infrastructure.schemas.activity import GitLabNote as GitLabNote
from .infrastructure.schemas.activity import PipelineJob as PipelineJob
from .infrastructure.schemas.pipelines import PipelineDetails as PipelineDetails
from .infrastructure.schemas.pipelines import PipelineSummary as PipelineSummary
from .repository_views import RepositoryResult as RepositoryResult
