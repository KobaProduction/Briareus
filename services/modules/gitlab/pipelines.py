"""Compatibility exports for the shared GitLab technical implementation."""

from source_control.providers.gitlab.pipelines import GitLabPipelineClient as GitLabPipelineClient

from .activity_views import JobTrace as JobTrace
from .activity_views import PipelineJobs as PipelineJobs
from .activity_views import PipelineList as PipelineList
from .activity_views import PipelineResult as PipelineResult
from .api import GitLabApiClient as GitLabApiClient
from .errors import GitLabError as GitLabError
from .infrastructure.schemas.activity import PipelineJobQuery as PipelineJobQuery
from .infrastructure.schemas.activity import PipelineJobRecords as PipelineJobRecords
from .infrastructure.schemas.activity import PipelineQuery as PipelineQuery
from .infrastructure.schemas.activity import PipelineRecords as PipelineRecords
from .infrastructure.schemas.pipelines import PipelineDetails as PipelineDetails
