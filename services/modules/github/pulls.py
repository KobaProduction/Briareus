from __future__ import annotations

from source_control.providers.github.pulls import GitHubPullClient as _SharedGitHubPullClient

from .application.merge import MergeCommand as MergeCommand
from .application.merge import MergePullRequest as MergePullRequest
from .application.merge import MergeReceipt as MergeReceipt
from .application.review_gates import CheckRunsReceipt as CheckRunsReceipt
from .application.review_gates import RequireChecks as RequireChecks
from .application.review_gates import RequiredChecksReceipt as RequiredChecksReceipt
from .base import GitHubRepositoryClientBase
from .collaboration_views import CommentCreated as CommentCreated
from .collaboration_views import CompactPull as CompactPull
from .collaboration_views import PullBranchUpdated as PullBranchUpdated
from .collaboration_views import PullDetails as PullDetails
from .collaboration_views import PullDetailsResponse as PullDetailsResponse
from .collaboration_views import PullFiles as PullFiles
from .collaboration_views import PullList as PullList
from .collaboration_views import PullResponse as PullResponse
from .collaboration_views import PullReviews as PullReviews
from .collaboration_views import ReviewSubmitted as ReviewSubmitted
from .comment_views import PullReviewSummary as PullReviewSummary
from .domain.merge import MergeError as MergeError
from .domain.mutations import MutationError as MutationError
from .domain.mutations import PullChange as PullChange
from .domain.mutations import ReviewEvent as ReviewEvent
from .domain.review_gates import ReviewGateError as ReviewGateError
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.merge import GitHubMerge as GitHubMerge
from .infrastructure.review_gates import GitHubReviewGates as GitHubReviewGates
from .infrastructure.schemas.collaboration import CommentBody as CommentBody
from .infrastructure.schemas.collaboration import ConversationRecord as ConversationRecord
from .infrastructure.schemas.collaboration import DiscussionQuery as DiscussionQuery
from .infrastructure.schemas.collaboration import PullBranchUpdate as PullBranchUpdate
from .infrastructure.schemas.collaboration import PullBranchUpdateResult as PullBranchUpdateResult
from .infrastructure.schemas.collaboration import PullCreate as PullCreate
from .infrastructure.schemas.collaboration import PullRecords as PullRecords
from .infrastructure.schemas.collaboration import PullRequestRecord as PullRequestRecord
from .infrastructure.schemas.collaboration import PullUpdate as PullUpdate
from .infrastructure.schemas.collaboration import ReviewCreate as ReviewCreate
from .infrastructure.schemas.collaboration import ReviewRecord as ReviewRecord
from .infrastructure.schemas.collaboration import ReviewRecords as ReviewRecords
from .infrastructure.schemas.repository import CommitFiles as CommitFiles


class GitHubPullClient(_SharedGitHubPullClient, GitHubRepositoryClientBase):
    pass
