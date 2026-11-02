"""Named github results; serialization stays at the MCP boundary."""

from pydantic import BaseModel

from .infrastructure.schemas.content import CodeMatch
from .ref_views import RepositoryResult


class DirectoryEntry(BaseModel):
    name: str
    path: str
    type: str
    size: int
    sha: str


class DirectoryListing(RepositoryResult):
    path: str
    ref: str | None
    entries: list[DirectoryEntry]


class RepositoryBinaryFile(RepositoryResult):
    path: str
    sha: str
    size: int
    content_base64: str


class RepositoryCodeSearch(RepositoryResult):
    total_count: int
    items: list[CodeMatch]
    page: int


class RepositoryContentDelete(RepositoryResult):
    branch: str
    path: str
    commit_sha: str


class RepositoryContentWrite(RepositoryResult):
    status: int
    operation: str
    branch: str
    path: str
    commit_sha: str
    content_sha: str


class RepositoryTextFile(RepositoryResult):
    path: str
    sha: str
    size: int
    content: str
