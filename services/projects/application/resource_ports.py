"""Owner facts required by reusable resource mutations."""

from typing import Protocol
from uuid import UUID


class ResourceOwnerRevision(Protocol):
    resource_revision: int


class ProjectOwnerRevision(ResourceOwnerRevision, Protocol):
    owner_team_id: UUID | None
    version: int
