from __future__ import annotations

from source_control.providers.github.refs import GitHubRefsClient as _SharedGitHubRefsClient

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError as GitHubAgentError
from .history_projection import git_identity as git_identity
from .history_projection import verification as verification
from .history_views import CommitSummary as CommitSummary
from .infrastructure.schemas.pagination import PageQuery as PageQuery
from .infrastructure.schemas.repository import AnnotatedTagCreate as AnnotatedTagCreate
from .infrastructure.schemas.repository import BranchRecord as BranchRecord
from .infrastructure.schemas.repository import BranchRecords as BranchRecords
from .infrastructure.schemas.repository import BranchRenameRequest as BranchRenameRequest
from .infrastructure.schemas.repository import CommitQuery as CommitQuery
from .infrastructure.schemas.repository import CommitRecords as CommitRecords
from .infrastructure.schemas.repository import ComparisonRecord as ComparisonRecord
from .infrastructure.schemas.repository import GitObjectId as GitObjectId
from .infrastructure.schemas.repository import GitReferenceCreate as GitReferenceCreate
from .infrastructure.schemas.repository import GitReferenceRecord as GitReferenceRecord
from .infrastructure.schemas.repository import GitReferenceUpdate as GitReferenceUpdate
from .infrastructure.schemas.repository import RepositoryCommitRecord as RepositoryCommitRecord
from .infrastructure.schemas.repository import TagRecords as TagRecords
from .ref_views import BranchDeletion as BranchDeletion
from .ref_views import BranchList as BranchList
from .ref_views import BranchMutationPolicy as BranchMutationPolicy
from .ref_views import BranchRename as BranchRename
from .ref_views import BranchResetApplied as BranchResetApplied
from .ref_views import BranchResetPlan as BranchResetPlan
from .ref_views import BranchSummary as BranchSummary
from .ref_views import BranchUpdate as BranchUpdate
from .ref_views import CommitList as CommitList
from .ref_views import CommitView as CommitView
from .ref_views import ComparedFile as ComparedFile
from .ref_views import RepositoryComparison as RepositoryComparison
from .ref_views import TagCreation as TagCreation
from .ref_views import TagDeletion as TagDeletion
from .ref_views import TagList as TagList
from .ref_views import TagSummary as TagSummary


class GitHubRefsClient(_SharedGitHubRefsClient, GitHubRepositoryClientBase):
    pass
