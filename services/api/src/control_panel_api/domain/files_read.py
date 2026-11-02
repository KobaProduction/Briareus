"""Files read evidence must remain bound to the same authority through final delivery."""

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .native_login import SecretText
from .oidc_identity import PrivateOidcResourceCredential
from .panel_protocol import PanelContext
from .platform_authority import PanelOidcSession

_RESERVED = re.compile(r"\.upload-[0-9a-f]{32}\.tmp\Z", re.ASCII)


def canonical_files_path(path: object) -> str:
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or not unicodedata.is_normalized("NFC", path)
    ):
        raise ValueError("relative NFC file path required")
    parts = path.split("/")
    try:
        if (
            len(path.encode("utf-8", errors="strict")) > 4096
            or len(parts) > 64
            or any(
                part in {"", ".", ".."}
                or len(part.encode("utf-8", errors="strict")) > 255
                or any(ord(char) < 32 or ord(char) == 127 for char in part)
                or _RESERVED.fullmatch(part) is not None
                for part in parts
            )
        ):
            raise ValueError("noncanonical Files path")
    except UnicodeError:
        raise ValueError("non-UTF-8 Files path") from None
    return path


@dataclass(frozen=True, slots=True)
class FilesReadRequest:
    project_uuid: UUID
    agent_session_uuid: UUID
    expected_grant_revision: int
    path: str
    max_bytes: int

    def __post_init__(self) -> None:
        canonical_files_path(self.path)
        if self.project_uuid.version != 4 or self.agent_session_uuid.version != 4:
            raise ValueError("Files read requires UUIDv4 project and session")
        if not 1 <= self.expected_grant_revision <= 2**63 - 1 or not 1 <= self.max_bytes <= 262144:
            raise ValueError("Files read revision and byte bound are invalid")


@dataclass(frozen=True, slots=True)
class PrivateFilesReadCommand:
    operation_uuid: UUID
    actor_uuid: UUID
    issuer: str
    subject: str
    project_uuid: UUID
    agent_session_uuid: UUID
    expected_grant_revision: int
    selector_id: str
    path: str
    max_bytes: int
    bearer: SecretText = field(repr=False)
    proof_expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedPrivateFilesRead:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int
    selector_id: str
    path: str
    payload: bytes = field(repr=False)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FilesContentDenied(Exception):
    """The independent Files/Access owner rejected the read effect."""


class FilesContentUnavailable(Exception):
    """Current owner/Project/Access/selector evidence could not be verified."""


def files_selector(project: UUID, path: str) -> str:
    material = b"files-project-relative-v1" + bytes([0]) + path.encode("utf-8")
    return f"project-path-v1:{project}:{hashlib.sha256(material).hexdigest()}"


def project_allows_read(context: PanelContext, project: UUID) -> bool:
    return (
        len(context.proof.projects) == 1
        and context.proof.projects[0].project_uuid == project
        and "use_resources" in context.proof.projects[0].permissions
    )


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def _revision(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _bounded_payload(value: object, maximum: int) -> bool:
    return type(value) is bytes and len(value) <= maximum


def valid_owner_read(
    result: object, command: PrivateFilesReadCommand, *, expires: datetime, now: datetime
) -> bool:
    if not isinstance(result, VerifiedPrivateFilesRead):
        return False
    return (
        result.operation_uuid == command.operation_uuid
        and result.actor_uuid == command.actor_uuid
        and result.project_uuid == command.project_uuid
        and result.agent_session_uuid == command.agent_session_uuid
        and _revision(result.grant_revision, command.expected_grant_revision)
        and result.selector_id == command.selector_id
        and result.path == command.path
        and _bounded_payload(result.payload, command.max_bytes)
        and _aware(result.checked_at)
        and _aware(result.expires_at)
        and result.checked_at <= now < result.expires_at
        and result.expires_at <= result.checked_at + timedelta(seconds=5)
        and expires > now
    )


def files_authority_continues(latest: PanelContext, original: PanelContext) -> bool:
    return (
        latest.session.issuer == original.session.issuer
        and latest.session.subject == original.session.subject
        and latest.session.client_id == original.session.client_id
        and latest.proof.user_uuid == original.proof.user_uuid
        and latest.proof.role == original.proof.role
        and len(latest.proof.projects) == 1
        and latest.proof.projects[0] == original.proof.projects[0]
        and "use_resources" in latest.proof.projects[0].permissions
    )


def files_session_continues(
    refreshed: PanelOidcSession | None,
    again: PrivateOidcResourceCredential | None,
    original: PanelContext,
    latest: PanelContext,
    credential: PrivateOidcResourceCredential,
    *,
    expires: datetime,
    owner_expires: datetime,
    now: datetime,
) -> bool:
    if refreshed is None or again is None:
        return False
    return (
        refreshed.issuer == original.session.issuer
        and refreshed.subject == original.session.subject
        and refreshed.client_id == original.session.client_id
        and again.subject == original.session.subject
        and hmac.compare_digest(
            again.bearer.get_secret_value(), credential.bearer.get_secret_value()
        )
        and min(
            refreshed.expires_at,
            latest.session.expires_at,
            latest.proof.expires_at,
            again.expires_at,
            expires,
            owner_expires,
        )
        > now
    )
