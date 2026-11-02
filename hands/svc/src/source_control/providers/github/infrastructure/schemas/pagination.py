"""Collection pagination parameters for GitHub provider requests."""

from pydantic import BaseModel


class PageQuery(BaseModel):
    page: int
    per_page: int
