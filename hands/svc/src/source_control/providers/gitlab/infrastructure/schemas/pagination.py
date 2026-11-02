"""Shared pagination parameters for GitLab collection endpoints."""

from pydantic import BaseModel


class PageQuery(BaseModel):
    page: int
    per_page: int
