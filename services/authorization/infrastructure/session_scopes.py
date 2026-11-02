"""Decode persisted/requested legacy scoped grants into typed owner facts."""

from uuid import UUID

from authorization._resource_scope import normalized_resource_grants
from authorization.domain.resource_scopes import canonical_grants
from authorization.domain.sessions import SessionResourceGrant


def decoded_resources(raw: object, grants: tuple[str, ...]) -> tuple[SessionResourceGrant, ...]:
    return normalized_resource_grants(raw, allowed_actions=set(grants))


def stored_resources(
    resources: tuple[SessionResourceGrant, ...] | None,
    grants: tuple[str, ...],
    project_uuid: UUID | None = None,
) -> tuple[SessionResourceGrant, ...]:
    if resources is None:
        raise ValueError("malformed stored session resource scopes")
    return canonical_grants(resources, set(grants), project_uuid)
