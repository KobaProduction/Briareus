"""GitHub issue, conversation and review schemas consumed by MCP projections."""

from typing import Literal

from pydantic import BaseModel, Field, RootModel, StrictBool

from source_control.providers.github.domain.mutations import ReviewEvent
from source_control.providers.github.history_views import ActorSource
from source_control.providers.github.models import ReviewComment

from .pagination import PageQuery
from .requests import GitHubRequestBody


class PullRequestLink(BaseModel):
    url: str | None = None
    html_url: str | None = None
    diff_url: str | None = None
    patch_url: str | None = None


class DiscussionRecord(BaseModel):
    number: int
    title: str
    state: str
    body: str | None = None
    html_url: str


class IssueRecord(DiscussionRecord):
    pull_request: PullRequestLink | None = None

    @property
    def is_pull_request(self) -> bool:
        return "pull_request" in self.model_fields_set


class IssueRecords(RootModel[list[IssueRecord]]):
    pass


class IssueCreate(GitHubRequestBody):
    title: str
    body: str
    labels: list[str] | None = None


class DiscussionUpdate(GitHubRequestBody):
    title: str | None = None
    body: str | None = None
    state: str | None = None


class IssueUpdate(DiscussionUpdate):
    labels: list[str] | None = None


class CommentBody(GitHubRequestBody):
    body: str


class ConversationRecord(BaseModel):
    id: int
    user: ActorSource | None = None
    body: str | None = None
    created_at: str
    updated_at: str
    html_url: str


class ConversationRecords(RootModel[list[ConversationRecord]]):
    pass


class ReviewCommentRecord(ConversationRecord):
    path: str
    line: int | None = None
    side: Literal["LEFT", "RIGHT"] | None = None
    commit_id: str


class ReviewCommentRecords(RootModel[list[ReviewCommentRecord]]):
    pass


class ReviewRecord(BaseModel):
    id: int
    user: ActorSource | None = None
    state: str
    body: str | None = None
    submitted_at: str | None = None
    commit_id: str | None = None


class ReviewRecords(RootModel[list[ReviewRecord]]):
    pass


class ReviewCreate(GitHubRequestBody):
    event: ReviewEvent
    body: str
    commit_id: str | None = None
    comments: list[ReviewComment] | None = None


class DiscussionQuery(PageQuery):
    state: str


class RepositoryReference(BaseModel):
    full_name: str


class PullRef(BaseModel):
    ref: str
    sha: str = Field(min_length=1)
    repo: RepositoryReference | None = None


class PullRequestRecord(DiscussionRecord):
    node_id: str
    head: PullRef
    base: PullRef
    draft: bool = False
    merged: bool = False
    mergeable: bool | None = None
    mergeable_state: str | None = None
    delete_source_branch_after_merge: bool | None = None


class PullRecords(RootModel[list[PullRequestRecord]]):
    pass


class PullCreate(GitHubRequestBody):
    title: str
    head: str
    base: str
    body: str
    draft: bool


class PullUpdate(DiscussionUpdate):
    base: str | None = None


class PullBranchUpdate(GitHubRequestBody):
    expected_head_sha: str | None = None


class PullBranchUpdateResult(BaseModel):
    message: str
    url: str | None = None


class TeamRecord(BaseModel):
    slug: str | None = None


class ReviewerRecords(BaseModel):
    requested_reviewers: list[ActorSource] = Field(default_factory=list)
    requested_teams: list[TeamRecord] = Field(default_factory=list)


class ReviewersRequest(GitHubRequestBody):
    reviewers: list[str] | None = None
    team_reviewers: list[str] | None = None


class ReviewCommentReplyRecord(ConversationRecord):
    in_reply_to_id: int | None = None


class BranchMergeRequest(GitHubRequestBody):
    base: str
    head: str
    commit_message: str | None = None


class PullMergeRequest(GitHubRequestBody):
    merge_method: str
    sha: str
    commit_title: str | None = None
    commit_message: str | None = None


class PullMergeResult(BaseModel):
    merged: StrictBool = False
    sha: str | None = None
    message: str | None = None
