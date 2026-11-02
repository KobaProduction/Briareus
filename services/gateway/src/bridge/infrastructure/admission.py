"""Bounded JSON adapter around an independently authenticated private peer."""

import json
from dataclasses import dataclass
from typing import Protocol

from bridge.domain.admission import ConnectionAdmission, ConnectionDecision, connection_decision


@dataclass(frozen=True, slots=True)
class PrivateAdmissionReply:
    status_code: int
    body: bytes


class TrustedGatewayDecisionPort(Protocol):
    """Real mTLS/Unix peer with exact decision bytes and nonce proof.

    A plain URL, caller Bearer, Docker DNS or header is not a service identity.
    No default peer implementation is supplied by Gateway.
    """

    async def decide(self, *, bearer: str, body: bytes, module: str) -> PrivateAdmissionReply: ...


@dataclass(frozen=True, slots=True)
class JsonMembers:
    members: tuple[tuple[str, object], ...]


def json_members(pairs: list[tuple[str, object]]) -> JsonMembers:
    # Preserve every pair; duplicates cannot disappear into a dictionary.
    return JsonMembers(tuple(pairs))


def exact_permit(payload: bytes) -> bool:
    if not payload or len(payload) > 4096:
        return False
    try:
        value: object = json.loads(payload, object_pairs_hook=json_members)
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(value, JsonMembers) or len(value.members) != 1:
        return False
    key, allowed = value.members[0]
    return key == "allowed" and allowed is True


def connection_command(admission: ConnectionAdmission) -> bytes:
    # Serialization remains at the external adapter; application returns no
    # generic dictionaries and does not know this owner's JSON schema.
    return json.dumps(
        {
            "project_uuid": str(admission.project_uuid),
            "agent_session_uuid": str(admission.agent_session_uuid),
            "action": "mcp.connect",
            "expected_grant_revision": admission.grant_revision,
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


class PrivateConnectionDecisions:
    def __init__(self, private: TrustedGatewayDecisionPort) -> None:
        self._private = private

    async def decide(self, admission: ConnectionAdmission) -> ConnectionDecision:
        wire = connection_command(admission)
        if not 0 < len(wire) <= 8192:
            return ConnectionDecision.UNAVAILABLE
        reply: object = await self._private.decide(
            bearer=admission.bearer, body=wire, module=admission.hand
        )
        if not isinstance(reply, PrivateAdmissionReply):
            return ConnectionDecision.UNAVAILABLE
        payload: object = reply.body
        permit = isinstance(payload, bytes) and exact_permit(payload)
        return connection_decision(reply.status_code, exact_permit=permit)
