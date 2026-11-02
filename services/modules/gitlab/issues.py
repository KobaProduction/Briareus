"""Compatibility exports for the shared GitLab technical implementation."""

from source_control.providers.gitlab.issues import GitLabIssueClient as GitLabIssueClient

from .activity_views import IssueList as IssueList
from .activity_views import IssueNote as IssueNote
from .activity_views import IssueResponse as IssueResponse
from .api import GitLabApiClient as GitLabApiClient
from .errors import GitLabError as GitLabError
from .infrastructure.schemas.activity import GitLabIssue as GitLabIssue
from .infrastructure.schemas.activity import GitLabNote as GitLabNote
from .infrastructure.schemas.activity import IssueCreate as IssueCreate
from .infrastructure.schemas.activity import IssueQuery as IssueQuery
from .infrastructure.schemas.activity import IssueRecords as IssueRecords
from .infrastructure.schemas.activity import IssueUpdate as IssueUpdate
from .infrastructure.schemas.activity import NoteCreate as NoteCreate
