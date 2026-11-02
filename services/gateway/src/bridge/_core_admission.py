"""Coarse admission over the existing authenticated Authorization owner peer."""

import base64
import json
from uuid import UUID

from node_protocol.module_effects import MODULES
from runtime_peer import PeerClient
from runtime_peer.response_decoding import confirmed_reply, successful_reply

from ._mcp_admission import McpAdmissionRejected
from .domain.admission import ConnectionAdmission
from .domain.call_outcome import CallOutcome
from .domain.node_forwarding import AuthorityEvidence, NodePlacement
from .infrastructure.admission import PrivateAdmissionReply
from .infrastructure.node_forwarding import authority_evidence


class CoreAdmission:
    def __init__(self, peer: PeerClient) -> None:
        self.peer = peer

    async def record_call(self, *, permit: str, status: CallOutcome, duration_ms: int) -> None:
        _owner_reply = await self.peer.call(
            "/internal/v1/authorization/mcp-call-outcome",
            {"permit": permit, "status": status, "duration_ms": duration_ms},
            decode=lambda status, value: confirmed_reply(status, value, "recorded"),
        )
        code, result = _owner_reply.status, _owner_reply.body
        if code != 200 or not result:
            raise ValueError("Call journal not confirmed")

    async def authorize_files(
        self,
        *,
        admission: ConnectionAdmission,
        route: NodePlacement,
        body: bytes,
        request_uuid: UUID,
    ) -> AuthorityEvidence:
        if admission.hand != "files":
            raise ValueError("Exact Files adapter required")
        return await self.authorize_module(
            admission=admission, route=route, body=body, request_uuid=request_uuid
        )

    async def authorize_terminal(
        self,
        *,
        admission: ConnectionAdmission,
        route: NodePlacement,
        body: bytes,
        request_uuid: UUID,
    ) -> AuthorityEvidence:
        if admission.hand != "terminal":
            raise ValueError("Exact Terminal adapter required")
        return await self.authorize_module(
            admission=admission, route=route, body=body, request_uuid=request_uuid
        )

    async def authorize_module(
        self,
        *,
        admission: ConnectionAdmission,
        route: NodePlacement,
        body: bytes,
        request_uuid: UUID,
    ) -> AuthorityEvidence:
        if admission.hand not in MODULES or route.module != admission.hand:
            raise ValueError("Approved exact Node module required")
        _owner_reply = await self.peer.call(
            "/internal/v1/authorization/node-" + admission.hand + "-effect",
            {
                "bearer": admission.bearer[7:],
                "module": admission.hand,
                "decision": {
                    "project_uuid": str(admission.project_uuid),
                    "agent_session_uuid": str(admission.agent_session_uuid),
                    "action": "mcp.connect",
                    "expected_grant_revision": admission.grant_revision,
                },
                "node_uuid": str(route.node_uuid),
                "placement_uuid": str(route.placement_uuid),
                "fingerprint": route.fingerprint,
                "request_uuid": str(request_uuid),
                "body": base64.b64encode(body).decode(),
            },
            decode=successful_reply(authority_evidence),
        )
        status, result = _owner_reply.status, _owner_reply.body
        if status in {401, 403}:
            raise McpAdmissionRejected("MCP_CURRENT_EFFECT_GRANT_REQUIRED", status)
        if status != 200 or result is None:
            raise ValueError("Current exact module effect authority unavailable")
        return result

    async def decide(self, *, bearer: str, body: bytes, module: str) -> PrivateAdmissionReply:
        if module not in MODULES or not bearer.startswith("Bearer ") or bearer.count(" ") != 1:
            raise ValueError("Exact resource-scoped connection required")
        command = json.loads(body)
        _owner_reply = await self.peer.call(
            "/internal/v1/authorization/mcp-admission",
            {"bearer": bearer[7:], "module": module, "decision": command},
            decode=lambda status, value: confirmed_reply(status, value, "allowed"),
        )
        status, result = _owner_reply.status, _owner_reply.body
        # A verified peer response is required by PeerClient.call. Error
        # bodies can never expose a token or be reinterpreted as a Permit.
        return PrivateAdmissionReply(
            status,
            b'{"allowed":true}' if status == 200 and result else b"{}",
        )
