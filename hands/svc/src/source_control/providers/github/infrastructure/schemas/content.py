"""Repository content records and signed file mutation bodies."""

from pydantic import BaseModel, RootModel

from .pagination import PageQuery
from .repository import CommitAuthors, GitObjectId, RepositoryFileIdentity


class ContentEntry(RepositoryFileIdentity):
    name: str
    path: str
    size: int = 0


class ContentEntries(RootModel[list[ContentEntry]]):
    pass


class ContentFile(ContentEntry):
    encoding: str
    content: str


class ContentMutation(CommitAuthors):
    message: str
    branch: str


class ContentWrite(ContentMutation):
    content: str
    sha: str | None = None


class ContentDelete(ContentMutation):
    sha: str


class ContentMutationResult(BaseModel):
    commit: GitObjectId
    content: GitObjectId | None = None


class CodeMatch(GitObjectId):
    name: str
    path: str


class CodeSearchResult(BaseModel):
    total_count: int
    items: list[CodeMatch]


class CodeSearchQuery(PageQuery):
    q: str
