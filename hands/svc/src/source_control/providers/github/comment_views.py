"""Public comment/review rows and the provider actor projection."""

from typing import Literal

from pydantic import BaseModel


class ConversationComment(BaseModel):
    id: int
    user: str
    body: str
    created_at: str
    updated_at: str
    html_url: str


class InlineReviewComment(BaseModel):
    id: int
    user: str
    path: str
    line: int | None
    side: Literal["LEFT", "RIGHT"] | None
    body: str
    commit_id: str
    html_url: str


class PullReviewSummary(BaseModel):
    id: int
    user: str
    state: str
    body: str
    submitted_at: str
