from __future__ import annotations

from source_control.providers.github.issues import GitHubIssueClient as _SharedGitHubIssueClient

from .base import GitHubRepositoryClientBase
from .collaboration_views import CommentCreated as CommentCreated
from .collaboration_views import CompactIssue as CompactIssue
from .collaboration_views import IssueList as IssueList
from .collaboration_views import IssueResponse as IssueResponse
from .domain.mutations import IssueChange as IssueChange
from .domain.mutations import MutationError as MutationError
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.collaboration import CommentBody as CommentBody
from .infrastructure.schemas.collaboration import ConversationRecord as ConversationRecord
from .infrastructure.schemas.collaboration import DiscussionQuery as DiscussionQuery
from .infrastructure.schemas.collaboration import IssueCreate as IssueCreate
from .infrastructure.schemas.collaboration import IssueRecord as IssueRecord
from .infrastructure.schemas.collaboration import IssueRecords as IssueRecords
from .infrastructure.schemas.collaboration import IssueUpdate as IssueUpdate


class GitHubIssueClient(_SharedGitHubIssueClient, GitHubRepositoryClientBase):
    pass
