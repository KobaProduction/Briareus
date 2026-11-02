"""Existing repository allowance delegation with the original concrete client ports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source_control.providers.github.base import GitHubRepositoryClientBase

    from .merge import MergeClient


class _AllowedRepository[ClientT: GitHubRepositoryClientBase | MergeClient]:
    __slots__ = ()
    client: ClientT

    def allowed(self, repository: str) -> str:
        return self.client._assert_allowed(repository)
