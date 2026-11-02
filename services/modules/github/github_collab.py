from __future__ import annotations

from source_control.providers.github.github_collab import (
    GitHubCollabClient as _SharedGitHubCollabClient,
)

from .application.review_gates import RequiredReviewsReceipt as RequiredReviewsReceipt
from .application.review_gates import RequireReviews as RequireReviews
from .collaboration_views import BranchAlreadyMerged as BranchAlreadyMerged
from .collaboration_views import BranchMerged as BranchMerged
from .collaboration_views import PullReady as PullReady
from .collaboration_views import RemovedReviewers as RemovedReviewers
from .collaboration_views import RequestedReviewers as RequestedReviewers
from .collaboration_views import ReviewCommentReply as ReviewCommentReply
from .collaboration_views import ReviewCommentUpdated as ReviewCommentUpdated
from .collaboration_views import ReviewThreadResolution as ReviewThreadResolution
from .collaboration_views import ReviewThreads as ReviewThreads
from .domain.review_gates import ReviewGateError as ReviewGateError
from .domain.review_threads import ReviewThread as ReviewThread
from .domain.review_threads import ThreadComment as ThreadComment
from .github_agent import GitHubAgentError as GitHubAgentError
from .github_review import GitHubReviewClient
from .infrastructure.review_gates import GitHubReviewGates as GitHubReviewGates
from .infrastructure.schemas.collaboration import BranchMergeRequest as BranchMergeRequest
from .infrastructure.schemas.collaboration import CommentBody as CommentBody
from .infrastructure.schemas.collaboration import ConversationRecord as ConversationRecord
from .infrastructure.schemas.collaboration import PullRequestRecord as PullRequestRecord
from .infrastructure.schemas.collaboration import (
    ReviewCommentReplyRecord as ReviewCommentReplyRecord,
)
from .infrastructure.schemas.collaboration import ReviewerRecords as ReviewerRecords
from .infrastructure.schemas.collaboration import ReviewersRequest as ReviewersRequest
from .infrastructure.schemas.graphql import GraphQLReply as GraphQLReply
from .infrastructure.schemas.graphql import GraphQLRequest as GraphQLRequest
from .infrastructure.schemas.graphql import PullNodeInput as PullNodeInput
from .infrastructure.schemas.graphql import PullNodeVariables as PullNodeVariables
from .infrastructure.schemas.graphql import ReadyPullData as ReadyPullData
from .infrastructure.schemas.graphql import ThreadQueryData as ThreadQueryData
from .infrastructure.schemas.graphql import ThreadQueryVariables as ThreadQueryVariables
from .infrastructure.schemas.graphql import ThreadResolutionData as ThreadResolutionData
from .infrastructure.schemas.graphql import ThreadResolutionInput as ThreadResolutionInput
from .infrastructure.schemas.graphql import ThreadResolutionVariables as ThreadResolutionVariables
from .infrastructure.schemas.repository import GitObjectId as GitObjectId
from .pulls import GitHubPullClient


class GitHubCollabClient(_SharedGitHubCollabClient, GitHubReviewClient, GitHubPullClient):
    pass
