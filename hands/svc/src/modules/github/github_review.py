from __future__ import annotations

from source_control.providers.github.github_review import (
    GitHubReviewClient as _SharedGitHubReviewClient,
)

from .base import GitHubRepositoryClientBase
from .comment_views import ConversationComment as ConversationComment
from .comment_views import InlineReviewComment as InlineReviewComment
from .domain.mutations import ReviewEvent as ReviewEvent
from .execution_views import ConversationComments as ConversationComments
from .execution_views import ReviewBranchUpdate as ReviewBranchUpdate
from .execution_views import ReviewComments as ReviewComments
from .execution_views import ReviewCreation as ReviewCreation
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.collaboration import ConversationRecords as ConversationRecords
from .infrastructure.schemas.collaboration import PullRequestRecord as PullRequestRecord
from .infrastructure.schemas.collaboration import ReviewCommentRecords as ReviewCommentRecords
from .infrastructure.schemas.collaboration import ReviewCreate as ReviewCreate
from .infrastructure.schemas.collaboration import ReviewRecord as ReviewRecord
from .infrastructure.schemas.graphql import BranchUpdateData as BranchUpdateData
from .infrastructure.schemas.graphql import GraphQLReply as GraphQLReply
from .infrastructure.schemas.graphql import GraphQLRequest as GraphQLRequest
from .infrastructure.schemas.graphql import UpdateBranchInput as UpdateBranchInput
from .infrastructure.schemas.graphql import UpdateBranchVariables as UpdateBranchVariables
from .infrastructure.schemas.pagination import PageQuery as PageQuery
from .models import ReviewComment as ReviewComment


class GitHubReviewClient(_SharedGitHubReviewClient, GitHubRepositoryClientBase):
    pass
