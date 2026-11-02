from __future__ import annotations

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError
from .history_projection import git_identity, verification
from .history_views import CommitSummary
from .infrastructure.schemas.pagination import PageQuery
from .infrastructure.schemas.repository import (
    AnnotatedTagCreate,
    BranchRecord,
    BranchRecords,
    BranchRenameRequest,
    CommitQuery,
    CommitRecords,
    ComparisonRecord,
    GitObjectId,
    GitReferenceCreate,
    GitReferenceRecord,
    GitReferenceUpdate,
    RepositoryCommitRecord,
    TagRecords,
)
from .ref_views import (
    BranchDeletion,
    BranchList,
    BranchMutationPolicy,
    BranchRename,
    BranchResetApplied,
    BranchResetPlan,
    BranchSummary,
    BranchUpdate,
    CommitList,
    CommitView,
    ComparedFile,
    RepositoryComparison,
    TagCreation,
    TagDeletion,
    TagList,
    TagSummary,
)


class GitHubRefsClient(GitHubRepositoryClientBase):
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
        elif github_protected:
            denial_reason = "branch is protected by GitHub"

        return BranchMutationPolicy(
            repository=repository,
            branch=branch,
            exists=exists,
            github_protected=github_protected,
            bridge_reserved=bridge_reserved,
            mutation_allowed=denial_reason is None,
            mutation_denial_reason=denial_reason,
        )

    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str:
        policy = self._branch_policy(repository, branch)
        reason = policy.mutation_denial_reason
        if reason:
            raise GitHubAgentError(f"{reason}: {branch}")
        return branch.strip()

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
            elif github_protected:
                denial_reason = "branch is protected by GitHub"
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

    def create_branch(self, repository: str, branch: str, from_branch: str) -> BranchUpdate:
        repository = self._assert_allowed(repository)
        source = self._quote(from_branch)
        ref = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{source}",
            response_type=GitReferenceRecord,
        ).data
        sha = ref.object.sha
        branch = self._assert_mutable_branch(branch)
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/git/refs",
            response_type=GitReferenceRecord,
            payload=GitReferenceCreate(ref=f"refs/heads/{branch}", sha=sha),
        ).data
        return BranchUpdate(repository=repository, branch=branch, sha=sha, result=result)

    def compare(self, repository: str, base: str, head: str) -> RepositoryComparison:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/compare/{self._quote(base)}...{self._quote(head)}",
            response_type=ComparisonRecord,
        ).data
        return RepositoryComparison(
            repository=repository,
            base=base,
            head=head,
            status=result.status,
            ahead_by=result.ahead_by,
            behind_by=result.behind_by,
            total_commits=result.total_commits,
            files=[
                ComparedFile(
                    filename=item.filename,
                    status=item.status,
                    additions=item.additions,
                    deletions=item.deletions,
                )
                for item in result.files
            ],
        )

    def list_commits(
        self,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> CommitList:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits",
            response_type=CommitRecords,
            query=CommitQuery(
                per_page=max(1, min(per_page, 100)),
                page=max(1, page),
                sha=ref or None,
                path=path or None,
            ),
        ).data.root
        commits = [
            CommitSummary(
                sha=item.sha,
                message=item.commit.message,
                author=git_identity(item.commit.author, item.author),
                committer=git_identity(item.commit.committer, item.committer),
                verification=verification(item.commit.verification, include_material=False),
                parents=[parent.sha for parent in item.parents],
            )
            for item in result
        ]
        return CommitList(repository=repository, commits=commits, page=page)

    def get_commit(self, repository: str, ref: str) -> CommitView:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}",
            response_type=RepositoryCommitRecord,
        ).data
        return CommitView(
            repository=repository,
            sha=result.sha,
            message=result.commit.message,
            tree_sha=result.commit.tree.sha,
            author=git_identity(result.commit.author, result.author),
            committer=git_identity(result.commit.committer, result.committer),
            verification=verification(result.commit.verification, include_material=True),
            parents=[parent.sha for parent in result.parents],
            files=result.files,
        )

    def delete_branch(self, repository: str, branch: str) -> BranchDeletion:
        repository = self._assert_allowed(repository)
        branch = self._assert_branch_mutation_allowed(repository, branch)
        self._repo_ack(
            repository, "DELETE", f"/repos/{repository}/git/refs/heads/{self._quote(branch)}"
        )
        return BranchDeletion(repository=repository, branch=branch, deleted=True)

    def rename_branch(
        self,
        repository: str,
        branch: str,
        new_name: str,
    ) -> BranchRename:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        new_name = self._assert_mutable_branch(new_name)
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/branches/{self._quote(branch)}/rename",
            response_type=BranchRecord,
            payload=BranchRenameRequest(new_name=new_name),
        ).data
        return BranchRename(
            repository=repository, old_branch=branch, new_branch=new_name, result=result
        )

    def fast_forward(self, repository: str, branch: str, to_ref: str) -> BranchUpdate:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        sha = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(to_ref)}",
            response_type=GitObjectId,
        ).data.sha
        result = self._repo_model(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{self._quote(branch)}",
            response_type=GitReferenceRecord,
            payload=GitReferenceUpdate(sha=sha, force=False),
        ).data
        return BranchUpdate(repository=repository, branch=branch, sha=sha, result=result)

    def reset_branch(
        self,
        repository: str,
        branch: str,
        target_ref: str,
        expected_head_sha: str,
        allow_protected_branch: bool = False,
        dry_run: bool = True,
    ) -> BranchResetPlan | BranchResetApplied:
        """Force-reset a branch to an existing ancestor commit with CAS safeguards."""
        repository = self._assert_allowed(repository)
        branch = branch.strip()
        target_ref = target_ref.strip()
        expected_head_sha = expected_head_sha.strip()
        if not branch:
            raise GitHubAgentError("branch must not be empty")
        if not target_ref:
            raise GitHubAgentError("target_ref must not be empty")
        if not expected_head_sha:
            raise GitHubAgentError("expected_head_sha must not be empty")
        if branch.casefold() in self.protected_branches and not allow_protected_branch:
            raise GitHubAgentError(
                f"reset of protected branch requires allow_protected_branch=true: {branch}"
            )

        branch_q = self._quote(branch)
        ref = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
            response_type=GitReferenceRecord,
        ).data
        head_sha = ref.object.sha
        if head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )

        target_sha = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(target_ref)}",
            response_type=GitObjectId,
        ).data.sha

        if target_sha != head_sha:
            comparison = self._repo_model(
                repository,
                "GET",
                f"/repos/{repository}/compare/{self._quote(target_sha)}...{self._quote(head_sha)}",
                response_type=ComparisonRecord,
            ).data
            if comparison.status != "ahead" or comparison.behind_by != 0:
                raise GitHubAgentError(
                    "target_ref must resolve to an ancestor of the current branch head"
                )

        result: BranchResetPlan = BranchResetPlan(
            repository=repository,
            branch=branch,
            previous_head_sha=head_sha,
            target_ref=target_ref,
            target_sha=target_sha,
            protected_branch_override=allow_protected_branch,
            dry_run=dry_run,
        )
        if dry_run or target_sha == head_sha:
            return result

        current_ref = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
            response_type=GitReferenceRecord,
        ).data
        current_head_sha = current_ref.object.sha
        if current_head_sha != head_sha:
            raise GitHubAgentError(
                f"branch head changed before reset: expected {head_sha}, found {current_head_sha}"
            )

        updated = self._repo_model(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            response_type=GitReferenceRecord,
            payload=GitReferenceUpdate(sha=target_sha, force=True),
        ).data
        return BranchResetApplied(
            repository=result.repository,
            branch=result.branch,
            previous_head_sha=result.previous_head_sha,
            target_ref=result.target_ref,
            target_sha=result.target_sha,
            protected_branch_override=result.protected_branch_override,
            dry_run=False,
            result=updated,
        )

    def list_tags(
        self,
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> TagList:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/tags",
            response_type=TagRecords,
            query=PageQuery(per_page=max(1, min(per_page, 100)), page=max(1, page)),
        ).data.root
        return TagList(
            repository=repository,
            tags=[TagSummary(name=item.name, sha=item.commit.sha) for item in result],
            page=page,
        )

    def create_tag(
        self,
        repository: str,
        tag: str,
        target_ref: str,
        message: str | None = None,
    ) -> TagCreation:
        repository = self._assert_allowed(repository)
        target_sha = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(target_ref)}",
            response_type=GitObjectId,
        ).data.sha
        ref_sha = target_sha
        annotated = bool(message)
        if message:
            ref_sha = self._repo_model(
                repository,
                "POST",
                f"/repos/{repository}/git/tags",
                response_type=GitObjectId,
                payload=AnnotatedTagCreate(tag=tag, message=message, object=target_sha),
            ).data.sha
        self._repo_ack(
            repository,
            "POST",
            f"/repos/{repository}/git/refs",
            payload=GitReferenceCreate(ref=f"refs/tags/{tag}", sha=ref_sha),
        )
        return TagCreation(
            repository=repository, tag=tag, target_sha=target_sha, annotated=annotated
        )

    def delete_tag(self, repository: str, tag: str) -> TagDeletion:
        repository = self._assert_allowed(repository)
        self._repo_ack(
            repository, "DELETE", f"/repos/{repository}/git/refs/tags/{self._quote(tag)}"
        )
        return TagDeletion(repository=repository, tag=tag, deleted=True)
