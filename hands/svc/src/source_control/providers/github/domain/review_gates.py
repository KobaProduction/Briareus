"""Required checks and independent approvals are evaluated against the current head."""

from dataclasses import dataclass


class ReviewGateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CheckRun:
    name: str
    status: str
    conclusion: str | None
    app: str
    details_url: str


class CheckSet:
    def __init__(self, checks: tuple[CheckRun, ...]) -> None:
        self.by_name = {check.name: check for check in checks}

    def matching(self, name: str) -> tuple[CheckRun, ...]:
        exact = self.by_name.get(name)
        if exact is not None:
            return (exact,)
        prefix = f"{name} ("
        return tuple(check for key, check in self.by_name.items() if key.startswith(prefix))

    def has_required_surface(self, required: tuple[str, ...]) -> bool:
        return any(self.matching(name) for name in required)

    def require_success(self, required: tuple[str, ...]) -> None:
        missing = [name for name in required if not self.matching(name)]
        failing = [
            name
            for name in required
            if any(
                check.status != "completed" or check.conclusion != "success"
                for check in self.matching(name)
            )
        ]
        if missing or failing:
            raise ReviewGateError(
                f"required checks not satisfied; missing={missing}, failing={failing}"
            )


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    state: str
    approved: bool


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    login: str
    state: str
    commit_id: str

    def at_head(self, head_sha: str) -> ReviewDecision:
        if self.state == "APPROVED" and self.commit_id == head_sha:
            return ReviewDecision(f"APPROVED@{self.commit_id}", True)
        if self.state == "APPROVED" and self.commit_id:
            return ReviewDecision(f"STALE_APPROVAL@{self.commit_id}", False)
        return ReviewDecision(self.state, False)


def require_current_reviews(
    required: tuple[str, ...],
    reviews: tuple[ReviewEvidence, ...],
    head_sha: str,
) -> None:
    decisive: dict[str, ReviewEvidence] = {}
    for review in reviews:
        if review.login and review.state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            decisive[review.login] = review
    missing: list[str] = []
    states: dict[str, str] = {}
    for login in required:
        decision = decisive.get(login, ReviewEvidence(login, "MISSING", "")).at_head(head_sha)
        states[login] = decision.state
        if not decision.approved:
            missing.append(login)
    if missing:
        raise ReviewGateError(
            "required independent reviews not satisfied for current PR head; "
            f"head={head_sha}, missing={missing}, states={states}"
        )
