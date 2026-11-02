"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import RootModel as RootModel

from modules.gitlab.models import GitLabCommitAction as GitLabCommitAction
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    BranchCreate as BranchCreate,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    BranchQuery as BranchQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    BranchRecords as BranchRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CodeMatch as CodeMatch,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CodeMatches as CodeMatches,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CodeSearchQuery as CodeSearchQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CommitActions as CommitActions,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CommitQuery as CommitQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CommitRecords as CommitRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CommitStats as CommitStats,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    CompareQuery as CompareQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    Comparison as Comparison,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    DiffRecords as DiffRecords,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    FileDelete as FileDelete,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    FileMutation as FileMutation,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    FileWrite as FileWrite,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    GitLabBranch as GitLabBranch,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    GitLabCommit as GitLabCommit,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    GitLabDiff as GitLabDiff,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    GitLabFile as GitLabFile,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import RefQuery as RefQuery
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    TreeEntry as TreeEntry,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    TreeQuery as TreeQuery,
)
from source_control.providers.gitlab.infrastructure.schemas.repository import (
    TreeRecords as TreeRecords,
)

from .pagination import PageQuery as PageQuery
from .pipelines import PipelineSummary as PipelineSummary
