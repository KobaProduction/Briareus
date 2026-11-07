"""Map one explicit provider claim to application roles; never search arbitrary claims."""

from __future__ import annotations

from briareus_json_values import JsonObject, JsonValue
from pydantic import TypeAdapter

from .settings import OidcTokenSettings

type OrganizationGrants = dict[str, str]
type ProjectRoles = dict[str, OrganizationGrants]
_GRANTS: TypeAdapter[ProjectRoles | list[ProjectRoles]] = TypeAdapter(
    ProjectRoles | list[ProjectRoles]
)
_ROLES = TypeAdapter(list[str])


def application_roles(payload: JsonObject, settings: OidcTokenSettings) -> tuple[str, ...]:
    value: JsonValue = payload
    for segment in settings.roles_claim_path:
        if not isinstance(value, dict) or segment not in value:
            raise ValueError("Required OIDC role claim is absent")
        value = value[segment]
    if settings.roles_format == "list":
        roles = set(_ROLES.validate_python(value, strict=True))
    else:
        grants = _GRANTS.validate_python(value, strict=True)
        groups = grants if isinstance(grants, list) else [grants]
        roles = {
            role
            for group in groups
            for role, organizations in group.items()
            if organizations.get(settings.roles_organization_id)
        }
    if settings.required_role not in roles:
        raise ValueError("Required OIDC application role is absent")
    return tuple(sorted(roles))
