"""Qualify a locked Resources lease before decrypting its owner credential."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from common.owner_contracts import OwnerCommandDTO
from common.platform_errors import AccessDenied
from projects._resource_persistence import CredentialLeaseRow


def current_credential_lease(
    lease: CredentialLeaseRow | None,
    request: OwnerCommandDTO,
    *,
    service_id: UUID,
    instance_uuid: UUID,
    audience: str,
    failure: str,
    required_kind: Literal["variable"] | None = None,
) -> CredentialLeaseRow:
    if (
        lease is None
        or (required_kind is not None and lease.kind != required_kind)
        or lease.project_id != request.project_id
        or lease.session_uuid != request.session_uuid
        or lease.user_id != request.caller_user_id
        or lease.service_id != service_id
        or lease.service_instance_uuid != instance_uuid
        or lease.service_audience != audience
        or lease.redeemed_at is not None
        or lease.expires_at <= datetime.now(UTC)
        or lease.session_version != request.expected_access_revision
        or lease.project_state_hash != format(request.expected_control_revision, "064x")
        or lease.project_resource_revision != request.expected_control_resource_revision
        or lease.team_state_hash
        != (
            format(request.expected_team_revision, "064x")
            if request.expected_team_revision is not None
            else None
        )
        or lease.team_resource_revision != request.expected_team_resource_revision
    ):
        raise AccessDenied(failure)
    return lease
