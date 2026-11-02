"""A coarse connection decision never grants a Hand business effect."""

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConnectionSelectors:
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int


def connection_selectors(project: str, session: str, revision: str) -> ConnectionSelectors:
    project_uuid, session_uuid = UUID(project), UUID(session)
    if not revision.isascii() or not revision.isdecimal():
        raise ValueError("Non-decimal grant revision")
    number = int(revision)
    if (
        project_uuid.version != 4
        or str(project_uuid) != project
        or session_uuid.version != 4
        or str(session_uuid) != session
        or not 1 <= number <= 2**63 - 1
        or str(number) != revision
    ):
        raise ValueError("Canonical UUIDv4 and positive grant revision required")
    return ConnectionSelectors(project_uuid, session_uuid, number)


@dataclass(frozen=True, slots=True)
class ConnectionAdmission:
    hand: str
    bearer: str
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int


@dataclass(frozen=True, slots=True)
class HumanAdmission:
    """Untrusted carrier; forwarding requires Core signature verification."""

    bearer: str
    project_uuid: UUID
    permit: str
    hand: str = "web"


type McpAdmission = ConnectionAdmission | HumanAdmission


class ConnectionDecision(Enum):
    PERMIT = "permit"
    IDENTITY_UNVERIFIED = "identity_unverified"
    ACCESS_DENIED = "access_denied"
    UNAVAILABLE = "unavailable"


def connection_decision(status: int, *, exact_permit: bool) -> ConnectionDecision:
    if status == 401:
        return ConnectionDecision.IDENTITY_UNVERIFIED
    if status == 403:
        return ConnectionDecision.ACCESS_DENIED
    if status == 200 and exact_permit:
        return ConnectionDecision.PERMIT
    return ConnectionDecision.UNAVAILABLE
