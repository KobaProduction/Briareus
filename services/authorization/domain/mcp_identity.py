"""A provider subject and a current Platform actor must describe one identity."""

from datetime import datetime, timedelta
from uuid import UUID

from authorization.domain.runtime_policy import RuntimeActor
from authorization.domain.workspace_effects import WorkspaceIdentity


class CurrentProjectDenied(ValueError):
    """Platform refused the provider subject's current Project membership."""


class ProjectContextLookupFailed(ValueError):
    def __init__(self, status: int) -> None:
        super().__init__("Current project identity unavailable")
        self.status = status


class InvalidCurrentIdentity(ValueError):
    """Current Platform/provider facts are inconsistent or expired."""


class McpGrantDenied(Exception):
    """The current Cedar grant does not permit coarse admission."""


class McpAuthorityExpired(Exception):
    """The grant expired before the admission result could be returned."""


def bind_current_identity(
    actor: RuntimeActor,
    *,
    issuer: str,
    subject: str,
    provider_expires_at: datetime,
    project_uuid: UUID,
    now: datetime,
) -> WorkspaceIdentity:
    scope_matches = (
        actor.issuer == issuer
        and actor.subject == subject
        and actor.project_uuid == project_uuid
        and actor.actor_uuid.version == 4
    )
    current = (
        "use_resources" in actor.permissions
        and actor.expires_at.tzinfo is not None
        and now < actor.expires_at <= now + timedelta(seconds=30)
        and provider_expires_at > now
    )
    if not (scope_matches and current):
        raise InvalidCurrentIdentity("Current project identity unavailable")
    return WorkspaceIdentity(
        issuer, subject, actor.actor_uuid, actor.expires_at, provider_expires_at
    )
