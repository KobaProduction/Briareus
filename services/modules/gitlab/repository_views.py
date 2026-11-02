"""Compatibility exports for the shared GitLab technical implementation."""

from dataclasses import dataclass as dataclass

from pydantic import BaseModel as BaseModel

from source_control.providers.gitlab.repository_views import GitSignature as GitSignature
from source_control.providers.gitlab.repository_views import RepositoryActions as RepositoryActions
from source_control.providers.gitlab.repository_views import (
    RepositoryBranchCreated as RepositoryBranchCreated,
)
from source_control.providers.gitlab.repository_views import (
    RepositoryBranchDeleted as RepositoryBranchDeleted,
)
from source_control.providers.gitlab.repository_views import (
    RepositoryBranches as RepositoryBranches,
)
from source_control.providers.gitlab.repository_views import RepositoryCommit as RepositoryCommit
from source_control.providers.gitlab.repository_views import RepositoryCommits as RepositoryCommits
from source_control.providers.gitlab.repository_views import (
    RepositoryComparison as RepositoryComparison,
)
from source_control.providers.gitlab.repository_views import RepositoryFile as RepositoryFile
from source_control.providers.gitlab.repository_views import (
    RepositoryFileDelete as RepositoryFileDelete,
)
from source_control.providers.gitlab.repository_views import (
    RepositoryFileWrite as RepositoryFileWrite,
)
from source_control.providers.gitlab.repository_views import RepositoryResult as RepositoryResult
from source_control.providers.gitlab.repository_views import RepositorySearch as RepositorySearch
from source_control.providers.gitlab.repository_views import RepositoryTree as RepositoryTree

from .infrastructure.schemas.repository import CodeMatch as CodeMatch
from .infrastructure.schemas.repository import Comparison as Comparison
from .infrastructure.schemas.repository import FileMutation as FileMutation
from .infrastructure.schemas.repository import GitLabBranch as GitLabBranch
from .infrastructure.schemas.repository import GitLabCommit as GitLabCommit
from .infrastructure.schemas.repository import GitLabDiff as GitLabDiff
from .infrastructure.schemas.repository import TreeEntry as TreeEntry
