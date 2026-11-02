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
    def _branch_policy(self, repository: str, branch: str) -> BranchMutationPolicy:
        repository = self._assert_allowed(repository)
        branch = branch.strip()
        if not branch:
            raise GitHubAgentError("branch must not be empty")

        result = self._repo_inspect_model(
            repository,
            "GET",
            f"/repos/{repository}/branches/{self._quote(branch)}",
            response_type=BranchRecord,
            unavailable_statuses={404},
        )
        exists = result is not None
        github_protected = result.protected if result is not None else False

        bridge_reserved = branch.casefold() in self.protected_branches
        denial_reason: str | None = None
        if bridge_reserved:
            denial_reason = "branch is reserved by bridge mutation policy"
        # GitHub rulesets may permit bypass; defer actual write authorization to GitHub.

        return BranchMutationPolicy(
            repository=repository,
            branch=branch,
            exists=exists,
            github_protected=github_protected,
            bridge_reserved=bridge_reserved,
            mutation_allowed=denial_reason is None,
            mutation_denial_reason=denial_reason,
        )

    def list_branches(self, repository: str) -> BranchList:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/branches?per_page=100",
            response_type=BranchRecords,
        ).data.root

        reserved = set(self.protected_branches)
        branches = []
        for item in result:
            name = item.name
            github_protected = item.protected
            bridge_reserved = name.casefold() in reserved
            denial_reason = None
            if bridge_reserved:
                denial_reason = "branch is reserved by bridge mutation policy"
            # github_protected is informational; it is not a Bridge push denial.
            branches.append(
                BranchSummary(
                    name=name,
                    sha=item.commit.sha,
                    protected=github_protected,
                    github_protected=github_protected,
                    bridge_reserved=bridge_reserved,
                    mutation_allowed=denial_reason is None,
                    mutation_denial_reason=denial_reason,
                )
            )
        return BranchList(repository=repository, branches=branches)
