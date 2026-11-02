from __future__ import annotations

from source_control.providers.github.git_transaction import (
    GitHubGitDataTransactionClient as _SharedGitHubGitDataTransactionClient,
)

from .application.mutations import BranchTransaction as BranchTransaction
from .application.mutations import CommitReceipt as CommitReceipt
from .base import GitHubRepositoryClientBase
from .domain.mutations import TreeChange as TreeChange
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.repository import GitCommitCreate as GitCommitCreate
from .infrastructure.schemas.repository import GitCommitRecord as GitCommitRecord
from .infrastructure.schemas.repository import GitObjectId as GitObjectId
from .infrastructure.schemas.repository import GitReferenceRecord as GitReferenceRecord
from .infrastructure.schemas.repository import GitReferenceUpdate as GitReferenceUpdate
from .infrastructure.schemas.repository import GitTreeChange as GitTreeChange
from .infrastructure.schemas.repository import GitTreeCreate as GitTreeCreate


class GitHubGitDataTransactionClient(
    _SharedGitHubGitDataTransactionClient, GitHubRepositoryClientBase
):
    pass
