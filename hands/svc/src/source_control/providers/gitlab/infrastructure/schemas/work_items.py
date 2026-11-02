"""Fields shared by GitLab issues and merge requests."""

from pydantic import BaseModel, Field

from .identity import GitLabUser


class GitLabWorkItem(BaseModel):
    id: int
    iid: int
    project_id: int
    title: str
    description: str | None = None
    state: str
    created_at: str
    updated_at: str
    author: GitLabUser | None = None
    assignees: list[GitLabUser] = Field(default_factory=list)
    assignee: GitLabUser | None = None
    labels: list[str] = Field(default_factory=list)
    web_url: str


class WorkItemUpdate(BaseModel):
    title: str | None
    description: str | None
    state_event: str | None
