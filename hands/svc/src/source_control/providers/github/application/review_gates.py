"""Fetch only the evidence needed to apply repository-specific current-head gates."""

from dataclasses import dataclass
from typing import Literal, Protocol

from source_control.providers.github.application._bindings import _ProviderBinding
from source_control.providers.github.domain.review_gates import (
    CheckRun,
    CheckSet,
    ReviewEvidence,
    require_current_reviews,
)


@dataclass(frozen=True, slots=True)
class CheckRunsReceipt:
    repository: str
    ref: str
    check_runs: tuple[CheckRun, ...]


@dataclass(frozen=True, slots=True)
class RequiredChecksReceipt:
    repository: str
    ref: str
    required: tuple[str, ...]
    status: Literal["ok", "delegated_to_github"]


@dataclass(frozen=True, slots=True)
class RequiredReviewsReceipt:
    repository: str
    number: int
    required_reviewers: tuple[str, ...]
    status: Literal["ok", "not_configured"]
    head_sha: str | None = None


class CheckProvider(Protocol):
    def checks(self, repository: str, ref: str) -> CheckRunsReceipt: ...
    def default_branch(self, repository: str) -> str: ...


class ReviewProvider(Protocol):
    def allowed(self, repository: str) -> str: ...
    def head(self, repository: str, number: int) -> str: ...
    def reviews(self, repository: str, number: int) -> tuple[ReviewEvidence, ...]: ...


class RequireChecks(_ProviderBinding[CheckProvider]):
    def execute(
        self, repository: str, ref: str, required: tuple[str, ...]
    ) -> RequiredChecksReceipt:
        head = CheckSet(self.provider.checks(repository, ref).check_runs)
        if required and not head.has_required_surface(required):
            default = self.provider.default_branch(repository)
            baseline = CheckSet(
                self.provider.checks(repository, default).check_runs if default else ()
            )
            if not baseline.has_required_surface(required):
                return RequiredChecksReceipt(repository, ref, required, "delegated_to_github")
        head.require_success(required)
        return RequiredChecksReceipt(repository, ref, required, "ok")


class RequireReviews(_ProviderBinding[ReviewProvider]):
    def execute(
        self, repository: str, number: int, required: tuple[str, ...]
    ) -> RequiredReviewsReceipt:
        repository = self.provider.allowed(repository)
        if not required:
            return RequiredReviewsReceipt(repository, number, required, "not_configured")
        head = self.provider.head(repository, number)
        require_current_reviews(required, self.provider.reviews(repository, number), head)
        return RequiredReviewsReceipt(repository, number, required, "ok", head)
