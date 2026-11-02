"""Build the existing pull metadata callback with its original registration metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .collaboration_views import PullDetailsResponse

if TYPE_CHECKING:
    from .github_actions import GitHubActionsClient


def _pull_request_reader(
    client_factory: Callable[[str], GitHubActionsClient],
    *,
    name: str,
) -> Callable[[str, str, int], PullDetailsResponse]:
    def get_pull_request(account_id: str, repository: str, number: int) -> PullDetailsResponse:
        """Read pull request metadata."""
        return client_factory(account_id).get_pull_request(repository, number)

    get_pull_request.__name__ = name
    return get_pull_request
