"""Field-exact GitLab MCP views; upstream documents stay at this provider boundary."""

from pydantic import BaseModel, ConfigDict

from .infrastructure.schemas.activity import GitLabNote
from .infrastructure.schemas.merge_requests import MergeRequest
from .infrastructure.schemas.repository import GitLabDiff


class ProjectReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_id: str
    project: str


class MergeRequestResult(ProjectReceipt):
    merge_request: MergeRequest


class MergeRequestPage(ProjectReceipt):
    merge_requests: list[MergeRequest]
    next_page: str


class MergeRequestDiffPage(ProjectReceipt):
    iid: int
    diffs: list[GitLabDiff]
    next_page: str


class MergeRequestNoteResult(ProjectReceipt):
    iid: int
    note: GitLabNote


type MergeRequestReceipt = (
    MergeRequestResult | MergeRequestPage | MergeRequestDiffPage | MergeRequestNoteResult
)
