"""Fail-closed owner readiness and private dispatch argument policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

OwnerServiceName = Literal["identity", "access", "control", "catalog"]
OWNER_SERVICES: tuple[OwnerServiceName, ...] = ("identity", "access", "control", "catalog")
_OWNER_STORE: dict[OwnerServiceName, str] = {
    "identity": "briareus_identity",
    "access": "briareus_access",
    "control": "briareus_platform",
    "catalog": "briareus_resources",
}


class ProjectGatewayDispatchUnavailable(Exception):
    """Redacted failure; an uncertain write retains its original operation UUID."""

    def __init__(self, code: str, *, operation_uuid: UUID | None = None) -> None:
        self.code = code
        self.operation_uuid = operation_uuid
        self.outcome_unknown = code in {
            "PROJECT_FILE_OUTCOME_UNKNOWN",
            "PROJECT_BACKEND_OUTCOME_UNKNOWN",
        }
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class VerifiedOwnerReadiness:
    """Recipient-bound snapshot supplied by an independently verifying port."""

    owner: OwnerServiceName
    database: str
    schema_head: str
    database_role: str
    owner_service_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExpectedOwnerSchema:
    """Trusted release expectation, independent of the owner's self-report."""

    owner: OwnerServiceName
    database: str
    expected_head: str
    expected_role: str
    expected_service_id: UUID


def require_matching_owner_schema(
    owner: OwnerServiceName,
    snapshot: VerifiedOwnerReadiness,
    expected: ExpectedOwnerSchema,
    *,
    now: datetime,
) -> None:
    """Compare identity, exact release and freshness before any protected effect."""
    if not isinstance(snapshot, VerifiedOwnerReadiness):
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if not isinstance(expected, ExpectedOwnerSchema):
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if snapshot.owner != owner or expected.owner != owner:
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if snapshot.database != _OWNER_STORE[owner] or expected.database != snapshot.database:
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    _require_revision(snapshot.schema_head, expected.expected_head)
    _require_revision(snapshot.database_role, expected.expected_role)
    _require_service_identity(snapshot.owner_service_id, expected.expected_service_id)
    _require_current_expiration(snapshot.expires_at, now)


def _require_revision(actual: str, expected: str) -> None:
    if not isinstance(actual, str):
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if not isinstance(expected, str):
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if actual != expected or not 1 <= len(actual) <= 128:
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")


def _require_service_identity(actual: UUID, expected: UUID) -> None:
    if not isinstance(actual, UUID):
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if actual.version != 4 or actual != expected:
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")


def _require_current_expiration(expires_at: datetime, now: datetime) -> None:
    if not isinstance(expires_at, datetime):
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if expires_at.tzinfo is None:
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")
    if expires_at <= now:
        raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_REVISION_INVALID")


def checked_request_uuid(value: UUID) -> UUID:
    if not isinstance(value, UUID):
        raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_INVALID")
    if value.version != 4:
        raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_INVALID")
    return value


@dataclass(slots=True)
class ArgumentBudget:
    visited: int = 0

    def visit(self, depth: int) -> None:
        if depth > 12:
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_TOO_DEEP")
        self.visited += 1
        if self.visited > 2048:
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_TOO_LARGE")
