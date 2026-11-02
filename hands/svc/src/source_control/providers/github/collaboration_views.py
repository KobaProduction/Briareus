"""GitHub pull request, issue and collaboration response contracts."""

from pydantic import BaseModel

from .comment_views import PullReviewSummary
from .domain.review_threads import ReviewThread
from .infrastructure.schemas.collaboration import PullBranchUpdateResult
from .ref_views import CommitFile, RepositoryResult


class CompactPull(BaseModel):
    number: int
    title: str
    state: str
    draft: bool
    head: str
    head_sha: str
    base: str
    merged: bool
    html_url: str
    delete_source_branch_after_merge: bool | None


class CompactIssue(BaseModel):
    number: int
    title: str
    state: str
    body: str
    html_url: str


class BranchAlreadyMerged(RepositoryResult):
    base: str
    head: str
    status: int
    merged: bool
    message: str


class BranchMerged(RepositoryResult):
    base: str
    head: str
    status: int
    merged: bool
    commit_sha: str


class CommentCreated(RepositoryResult):
    number: int
    comment_id: int
    html_url: str


class IssueCommentDeleted(RepositoryResult):
    comment_id: int
    deleted: bool


class IssueCommentUpdated(RepositoryResult):
    comment_id: int
    html_url: str
    body: str
    updated: bool


class IssueList(RepositoryResult):
    issues: list[CompactIssue]
    page: int


class IssuePage(IssueList):
    per_page: int
    count: int
    raw_count: int
    has_next: bool
    next_page: int | None


class IssueResponse(RepositoryResult):
    issue: CompactIssue


class PullBranchUpdated(RepositoryResult):
    number: int
    result: PullBranchUpdateResult


class PullFiles(RepositoryResult):
    number: int
    files: list[CommitFile]


class PullList(RepositoryResult):
    pull_requests: list[CompactPull]
    page: int


class PullReady(RepositoryResult):
    number: int
    draft: bool


class PullResponse(RepositoryResult):
    pull_request: CompactPull


class PullReviews(RepositoryResult):
    number: int
    reviews: list[PullReviewSummary]


class RemovedReviewers(RepositoryResult):
    number: int
    removed: bool


class RequestedReviewers(RepositoryResult):
    number: int
    reviewers: list[str]
    teams: list[str]


class ReviewCommentReply(RepositoryResult):
    number: int
    comment_id: int
    in_reply_to_id: int
    html_url: str


class ReviewCommentUpdated(RepositoryResult):
    comment_id: int
    body: str
    html_url: str


class ReviewSubmitted(RepositoryResult):
    number: int
    review_id: int
    state: str


class ReviewThreadResolution(RepositoryResult):
    thread_id: str
    resolved: bool


class ReviewThreads(RepositoryResult):
    number: int
    threads: tuple[ReviewThread, ...]


class PullDetails(CompactPull):
    body: str
    mergeable: bool | None
    mergeable_state: str


class PullDetailsResponse(RepositoryResult):
    pull_request: PullDetails
