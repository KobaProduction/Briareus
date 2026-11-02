"""Concrete GitHub GraphQL selections and a reusable typed protocol envelope."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from source_control.providers.github.history_views import ActorSource

from .requests import GitHubRequestBody


class GraphQLFields(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class GraphQLLocation(BaseModel):
    line: int
    column: int


class GraphQLError(BaseModel):
    message: str
    path: list[str | int] = Field(default_factory=list)
    locations: list[GraphQLLocation] = Field(default_factory=list)


class GraphQLReply[T: BaseModel](BaseModel):
    data: T | None = None
    errors: list[GraphQLError] = Field(default_factory=list)


class GraphQLRequest[V: BaseModel](GitHubRequestBody):
    query: str
    variables: V


class UpdateBranchInput(GraphQLFields):
    pull_request_id: str = Field(alias="pullRequestId")
    update_method: str = Field(alias="updateMethod")
    expected_head_oid: str | None = Field(default=None, alias="expectedHeadOid")


class UpdateBranchVariables(BaseModel):
    input: UpdateBranchInput


class UpdatedPull(GraphQLFields):
    number: int
    head_ref_name: str = Field(alias="headRefName")
    head_ref_oid: str = Field(alias="headRefOid")
    base_ref_name: str = Field(alias="baseRefName")
    mergeable: str


class BranchUpdatePayload(GraphQLFields):
    pull_request: UpdatedPull = Field(alias="pullRequest")


class BranchUpdateData(GraphQLFields):
    update_pull_request_branch: BranchUpdatePayload = Field(alias="updatePullRequestBranch")


class ThreadQueryVariables(BaseModel):
    owner: str
    name: str
    number: int


class ThreadCommentRecord(GraphQLFields):
    id: str
    database_id: int | None = Field(default=None, alias="databaseId")
    body: str
    author: ActorSource | None = None
    created_at: str = Field(alias="createdAt")
    url: str


class ThreadComments(BaseModel):
    nodes: list[ThreadCommentRecord]


class ThreadState(GraphQLFields):
    id: str
    is_resolved: StrictBool = Field(alias="isResolved")


class ThreadRecord(ThreadState):
    is_outdated: StrictBool = Field(alias="isOutdated")
    path: str
    line: int | None = None
    start_line: int | None = Field(default=None, alias="startLine")
    comments: ThreadComments


class ThreadConnection(BaseModel):
    nodes: list[ThreadRecord]


class PullThreadConnection(GraphQLFields):
    review_threads: ThreadConnection = Field(alias="reviewThreads")


class RepositoryThreads(GraphQLFields):
    pull_request: PullThreadConnection = Field(alias="pullRequest")


class ThreadQueryData(BaseModel):
    repository: RepositoryThreads


class ThreadResolutionInput(GraphQLFields):
    thread_id: str = Field(alias="threadId")


class ThreadResolutionVariables(BaseModel):
    input: ThreadResolutionInput


class ThreadResolutionPayload(BaseModel):
    thread: ThreadState


class ThreadResolutionData(GraphQLFields):
    resolve_review_thread: ThreadResolutionPayload | None = Field(
        default=None, alias="resolveReviewThread"
    )
    unresolve_review_thread: ThreadResolutionPayload | None = Field(
        default=None, alias="unresolveReviewThread"
    )


class PullNodeInput(GraphQLFields):
    pull_request_id: str = Field(alias="pullRequestId")


class PullNodeVariables(BaseModel):
    input: PullNodeInput


class ReadyPull(GraphQLFields):
    number: int
    is_draft: StrictBool = Field(alias="isDraft")


class ReadyPullPayload(GraphQLFields):
    pull_request: ReadyPull = Field(alias="pullRequest")


class ReadyPullData(GraphQLFields):
    mark_pull_request_ready_for_review: ReadyPullPayload = Field(
        alias="markPullRequestReadyForReview"
    )
