"""GitHub review and check-run codecs keep provider responses outside the domain."""

from dataclasses import dataclass

from source_control.providers.github.application.review_gates import CheckRunsReceipt
from source_control.providers.github.base import GitHubRepositoryClientBase
from source_control.providers.github.domain.review_gates import CheckRun, ReviewEvidence

from ._repository_gate import _AllowedRepository
from .schemas.actions import CheckRunRecord, CheckRuns
from .schemas.collaboration import PullRequestRecord, ReviewRecords


def check_run(item: CheckRunRecord) -> CheckRun:
    return CheckRun(
        item.name or "",
        item.status,
        item.conclusion,
        item.app.slug or "" if item.app else "",
        item.details_url or "",
    )


@dataclass(frozen=True, slots=True)
class GitHubReviewGates(_AllowedRepository[GitHubRepositoryClientBase]):
    client: GitHubRepositoryClientBase

    def checks(self, repository: str, ref: str) -> CheckRunsReceipt:
        repository = self.client._assert_allowed(repository)
        result = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self.client._quote(ref)}/check-runs?per_page=100",
            response_type=CheckRuns,
        ).data
        return CheckRunsReceipt(
            repository, ref, tuple(check_run(item) for item in result.check_runs)
        )

    def default_branch(self, repository: str) -> str:
        return self.client._repository_metadata(repository).default_branch

    def head(self, repository: str, number: int) -> str:
        result = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
            response_type=PullRequestRecord,
        ).data
        return result.head.sha

    def reviews(self, repository: str, number: int) -> tuple[ReviewEvidence, ...]:
        result = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
            response_type=ReviewRecords,
        ).data.root
        return tuple(
            ReviewEvidence(
                (item.user.login or "").casefold() if item.user else "",
                item.state.upper(),
                item.commit_id or "",
            )
            for item in result
        )
