from __future__ import annotations

from source_control.providers.github.content_api import (
    GitHubContentApiClient as _SharedGitHubContentApiClient,
)

from .base import GitHubRepositoryClientBase
from .content_views import DirectoryEntry as DirectoryEntry
from .content_views import DirectoryListing as DirectoryListing
from .content_views import RepositoryBinaryFile as RepositoryBinaryFile
from .content_views import RepositoryCodeSearch as RepositoryCodeSearch
from .content_views import RepositoryContentDelete as RepositoryContentDelete
from .content_views import RepositoryContentWrite as RepositoryContentWrite
from .content_views import RepositoryTextFile as RepositoryTextFile
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.content import CodeSearchQuery as CodeSearchQuery
from .infrastructure.schemas.content import CodeSearchResult as CodeSearchResult
from .infrastructure.schemas.content import ContentDelete as ContentDelete
from .infrastructure.schemas.content import ContentEntries as ContentEntries
from .infrastructure.schemas.content import ContentFile as ContentFile
from .infrastructure.schemas.content import ContentMutationResult as ContentMutationResult
from .infrastructure.schemas.content import ContentWrite as ContentWrite
from .infrastructure.schemas.repository import RepositoryFileIdentity as RepositoryFileIdentity


class GitHubContentApiClient(_SharedGitHubContentApiClient, GitHubRepositoryClientBase):
    pass
