from __future__ import annotations

import base64 as base64
import subprocess as subprocess
import urllib as urllib
from pathlib import Path as Path
from typing import Never

from common.repository_checkout import checkout_repository as checkout_repository
from source_control.providers.gitlab.repository import (
    GitLabRepositoryOperations as _GitLabRepositoryOperations,
)

from .api import GitLabApiClient as GitLabApiClient
from .errors import GitLabError as GitLabError
from .infrastructure.schemas.identity import AuthenticatedGitLabUser as AuthenticatedGitLabUser
from .infrastructure.schemas.repository import BranchCreate as BranchCreate
from .infrastructure.schemas.repository import BranchQuery as BranchQuery
from .infrastructure.schemas.repository import BranchRecords as BranchRecords
from .infrastructure.schemas.repository import CodeMatches as CodeMatches
from .infrastructure.schemas.repository import CodeSearchQuery as CodeSearchQuery
from .infrastructure.schemas.repository import CommitActions as CommitActions
from .infrastructure.schemas.repository import CommitQuery as CommitQuery
from .infrastructure.schemas.repository import CommitRecords as CommitRecords
from .infrastructure.schemas.repository import CompareQuery as CompareQuery
from .infrastructure.schemas.repository import Comparison as Comparison
from .infrastructure.schemas.repository import DiffRecords as DiffRecords
from .infrastructure.schemas.repository import FileDelete as FileDelete
from .infrastructure.schemas.repository import FileMutation as FileMutation
from .infrastructure.schemas.repository import FileWrite as FileWrite
from .infrastructure.schemas.repository import GitLabBranch as GitLabBranch
from .infrastructure.schemas.repository import GitLabCommit as GitLabCommit
from .infrastructure.schemas.repository import GitLabFile as GitLabFile
from .infrastructure.schemas.repository import RefQuery as RefQuery
from .infrastructure.schemas.repository import TreeQuery as TreeQuery
from .infrastructure.schemas.repository import TreeRecords as TreeRecords
from .local_git_views import GitLabCheckout as GitLabCheckout
from .local_git_views import GitLabGitAuthorization as GitLabGitAuthorization
from .local_git_views import GitLabGitPush as GitLabGitPush
from .models import GitLabCommitAction as GitLabCommitAction
from .policy import require_mutable_branch as require_mutable_branch
from .repository_views import GitSignature as GitSignature
from .repository_views import RepositoryActions as RepositoryActions
from .repository_views import RepositoryBranchCreated as RepositoryBranchCreated
from .repository_views import RepositoryBranchDeleted as RepositoryBranchDeleted
from .repository_views import RepositoryBranches as RepositoryBranches
from .repository_views import RepositoryCommit as RepositoryCommit
from .repository_views import RepositoryCommits as RepositoryCommits
from .repository_views import RepositoryComparison as RepositoryComparison
from .repository_views import RepositoryFile as RepositoryFile
from .repository_views import RepositoryFileDelete as RepositoryFileDelete
from .repository_views import RepositoryFileWrite as RepositoryFileWrite
from .repository_views import RepositorySearch as RepositorySearch
from .repository_views import RepositoryTree as RepositoryTree


class GitLabRepositoryClient(_GitLabRepositoryOperations[Never, Never, Never]):
    """Legacy receipt family with no additional local transport results."""
