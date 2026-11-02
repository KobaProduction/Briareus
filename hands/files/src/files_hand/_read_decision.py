"""Strict binding of authenticated private Access replies to one native read.

This decoder is NOT transport authentication or a permission issuer. Only
an independently authenticated Files/Access adapter may pass replies here;
the original Rauthy token, phase-specific nonce and actual root mapping
must be checked by their owners. Never accept this JSON from an MCP caller.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictBool, StrictInt, StrictStr

from ._native_read import NativeFilesReadRequest
from ._read_adapter import FilesMcpReadUnavailable

ReadPhase = Literal["before_read", "after_read"]
READ_DECISION_PATH = "/internal/v1/authorization/files/read-decision"
_PROTOCOL = "files-read-decision-v1"


@dataclass(frozen=True, slots=True)
class FilesReadDecisionRequest:
    request: NativeFilesReadRequest
    resource_revision: int
    phase: ReadPhase

    def __post_init__(self) -> None:
        if not isinstance(self.request, NativeFilesReadRequest):
            raise FilesMcpReadUnavailable("FILES_DECISION_REQUEST_INVALID")
        if (
            type(self.resource_revision) is not int
            or not 1 <= self.resource_revision <= 2**63 - 1
            or self.phase not in {"before_read", "after_read"}
        ):
            raise FilesMcpReadUnavailable("FILES_DECISION_REQUEST_INVALID")

    def wire_body(self) -> bytes:
        request = self.request
        return json.dumps(
            {
                "protocol": _PROTOCOL,
                "operation_uuid": str(request.request_uuid),
                "phase": self.phase,
                "project_uuid": str(request.project_uuid),
                "agent_session_uuid": str(request.agent_session_uuid),
                "expected_grant_revision": request.expected_grant_revision,
                "expected_resource_revision": self.resource_revision,
                "max_bytes": request.arguments.max_bytes,
                "hand": "files",
                "tool": "read_file",
                "action": "files.read",
                "resource": asdict(request.selector.decision_resource()),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class FilesReadDecisionReceipt:
    """Validated data from a private reply, not a transferable signed token."""

    command: FilesReadDecisionRequest
    actor_uuid: UUID
    checked_at: datetime
    expires_at: datetime

    def final_deadline(self, previous: FilesReadDecisionReceipt, *, now: datetime) -> datetime:
        if (
            self.command.phase != "after_read"
            or previous.command.phase != "before_read"
            or self.command.request != previous.command.request
            or self.command.resource_revision != previous.command.resource_revision
            or self.actor_uuid != previous.actor_uuid
            or self.checked_at < previous.checked_at
            or now.tzinfo is None
            or not self.checked_at <= now < min(self.expires_at, previous.expires_at)
        ):
            raise FilesMcpReadUnavailable("FILES_DECISION_PHASE_BINDING_INVALID")
        return min(self.expires_at, previous.expires_at)


@dataclass(frozen=True, slots=True)
class JsonObjectPairs:
    """Raw JSON parser node; neither an accepted reply nor authority."""

    pairs: tuple[tuple[str, object], ...]


def _unique_fields(pairs: list[tuple[str, object]]) -> JsonObjectPairs:
    names = [key for key, _ in pairs]
    if len(set(names)) != len(names):
        raise ValueError("duplicate Access reply field")
    return JsonObjectPairs(tuple(pairs))


class _ReadDecisionResource(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    kind: StrictStr
    id: StrictStr


class _ReadDecisionReply(BaseModel):
    """Exact private wire observation; it carries no transport authority."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    protocol: Literal["files-read-decision-v1"]
    allowed: StrictBool
    operation_uuid: StrictStr
    phase: ReadPhase
    actor_uuid: StrictStr
    project_uuid: StrictStr
    agent_session_uuid: StrictStr
    hand: Literal["files"]
    tool: Literal["read_file"]
    action: Literal["files.read"]
    resource: _ReadDecisionResource
    grant_revision: StrictInt
    resource_revision: StrictInt
    max_bytes: StrictInt
    checked_at: Annotated[datetime, BeforeValidator(datetime.fromisoformat)]
    expires_at: Annotated[datetime, BeforeValidator(datetime.fromisoformat)]


def _reply_matches(
    reply: _ReadDecisionReply, command: FilesReadDecisionRequest, expected_actor_uuid: UUID
) -> bool:
    request = command.request
    resource = request.selector.decision_resource()
    return (
        reply.operation_uuid == str(request.request_uuid)
        and reply.phase == command.phase
        and reply.actor_uuid == str(expected_actor_uuid)
        and reply.project_uuid == str(request.project_uuid)
        and reply.agent_session_uuid == str(request.agent_session_uuid)
        and reply.resource.kind == resource.kind
        and reply.resource.id == resource.id
        and reply.grant_revision == request.expected_grant_revision
        and reply.resource_revision == command.resource_revision
        and reply.max_bytes == request.arguments.max_bytes
    )


def decode_private_read_decision(
    *,
    command: FilesReadDecisionRequest,
    status: int,
    body: bytes,
    expected_actor_uuid: UUID,
    now: datetime | None = None,
) -> FilesReadDecisionReceipt:
    """Check exact original request + verified actor supplied by private peer.

    No raw bearer/JWKS/HTTP headers belong here. The adapter MUST reject
    unverified HTTP origins or stale body-bound nonces before this decoder.
    Both phases use new authenticated requests, not cached receipt reuse.
    """
    try:
        _require_reply_envelope(command, status, body, expected_actor_uuid)
        # Reject duplicate fields before validating the named wire observation.
        json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_unique_fields)
        reply = _ReadDecisionReply.model_validate(json.loads(body), strict=True)
        if reply.allowed is not True or not _reply_matches(reply, command, expected_actor_uuid):
            raise ValueError("original Files read binding changed")
        checked, expires = reply.checked_at, reply.expires_at
        current = datetime.now(UTC) if now is None else now
        if (
            checked.tzinfo is None
            or expires.tzinfo is None
            or current.tzinfo is None
            or not checked <= current < expires <= checked + timedelta(seconds=5)
        ):
            raise ValueError("stale or excessive read proof lifetime")
        return FilesReadDecisionReceipt(command, expected_actor_uuid, checked, expires)
    except (TypeError, ValueError, UnicodeError, KeyError, RecursionError):
        raise FilesMcpReadUnavailable("FILES_DECISION_REPLY_INVALID") from None


def _require_reply_envelope(
    command: FilesReadDecisionRequest, status: int, body: bytes, expected_actor_uuid: UUID
) -> None:
    if not isinstance(command, FilesReadDecisionRequest):
        raise ValueError("private reply shape")
    if not isinstance(expected_actor_uuid, UUID):
        raise ValueError("private reply shape")
    if (
        type(status) is not int
        or status != 200
        or type(body) is not bytes
        or (not 0 < len(body) <= 8192)
        or (expected_actor_uuid.version != 4)
    ):
        raise ValueError("private reply shape")
