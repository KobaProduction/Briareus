"""An empty Platform trust root needs an independently approved provider admin."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from projects.domain.context import current_expiry
from projects.domain.management import ManagementError, name
from projects.domain.membership import valid_uuid4
from projects.domain.user_links import VerifiedRauthyUserStatus, canonical_subject


class FirstOperatorBootstrapDenied(Exception):
    """Initial operator proof or the empty-owner invariant failed."""


class FirstOperatorBootstrapUnavailable(Exception):
    """Provider authority or the owner database cannot confirm the operation."""


@dataclass(frozen=True, slots=True)
class VerifiedFirstOperatorApproval:
    operation_uuid: UUID
    user_uuid: UUID
    rauthy_issuer: str
    rauthy_subject: str
    audience: Literal["briareus:platform:first-operator"]
    provider_admin_verified: bool
    independent_owner_approval: bool
    bootstrap_project_uuid: UUID
    bootstrap_project_name: str
    expires_at: datetime


def bootstrap_audience(value: object) -> bool:
    return value == "briareus:platform:first-operator"


def project_name(value: object) -> bool:
    try:
        return name(value) == value
    except ManagementError:
        return False


def verified_approval(
    value: object,
    allowed_issuers: frozenset[str],
    now: datetime,
) -> VerifiedFirstOperatorApproval:
    if not isinstance(value, VerifiedFirstOperatorApproval):
        raise FirstOperatorBootstrapDenied("signed first-operator approval required")
    identities = (value.operation_uuid, value.user_uuid, value.bootstrap_project_uuid)
    if not all(valid_uuid4(uuid) for uuid in identities):
        raise FirstOperatorBootstrapDenied("canonical first-operator identities required")
    if not bootstrap_audience(value.audience) or value.rauthy_issuer not in allowed_issuers:
        raise FirstOperatorBootstrapDenied("first-operator provider or audience invalid")
    if not canonical_subject(value.rauthy_subject):
        raise FirstOperatorBootstrapDenied("canonical Rauthy administrator subject required")
    if value.provider_admin_verified is not True or value.independent_owner_approval is not True:
        raise FirstOperatorBootstrapDenied("independent Rauthy administrator approval required")
    if not project_name(value.bootstrap_project_name) or not current_expiry(value.expires_at, now):
        raise FirstOperatorBootstrapDenied(
            "fresh first-operator approval and project name required"
        )
    return value


def require_active_status(
    value: object,
    approval: VerifiedFirstOperatorApproval,
    now: datetime,
) -> VerifiedRauthyUserStatus:
    if not isinstance(value, VerifiedRauthyUserStatus):
        raise FirstOperatorBootstrapDenied("existing active Rauthy admin subject required")
    if value.issuer != approval.rauthy_issuer or value.subject != approval.rauthy_subject:
        raise FirstOperatorBootstrapDenied("provider User identity mismatch")
    if value.active is not True or not current_expiry(value.expires_at, now):
        raise FirstOperatorBootstrapDenied("existing active Rauthy admin subject required")
    return value
