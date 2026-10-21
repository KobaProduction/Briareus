"""Coarse admission over the existing authenticated Authorization owner peer."""
import json
import base64

from node_protocol.module_effects import MODULES
from node_protocol.files import strict_json

from ._mcp_admission import PrivateAdmissionReply,McpAdmissionRejected


class CoreAdmission:
    def __init__(self, peer):
        self.peer = peer

    async def record_call(self, *, permit, status, duration_ms):
        code, result = await self.peer.call("/internal/v1/authorization/mcp-call-outcome",
            {"permit":permit, "status":status, "duration_ms":duration_ms})
        if code != 200 or result != {"recorded":True}:
            raise ValueError("Call journal not confirmed")

    async def authorize_files(self, *, admission, route, body, request_uuid):
        if admission.hand != "files":
            raise ValueError("Exact Files adapter required")
        return await self.authorize_module(admission=admission, route=route, body=body, request_uuid=request_uuid)

    async def authorize_terminal(self, *, admission, route, body, request_uuid):
        if admission.hand != "terminal":
            raise ValueError("Exact Terminal adapter required")
        return await self.authorize_module(admission=admission, route=route, body=body, request_uuid=request_uuid)

    async def authorize_module(self, *, admission, route, body, request_uuid):
        if admission.hand not in MODULES or route.module != admission.hand:
            raise ValueError("Approved exact Node module required")
        status, result = await self.peer.call("/internal/v1/authorization/node-" + admission.hand + "-effect", {
            "bearer": admission.bearer[7:], "module": admission.hand,
            "decision": {"project_uuid": str(admission.project_uuid),
                "agent_session_uuid": str(admission.agent_session_uuid), "action": "mcp.connect",
                "expected_grant_revision": admission.grant_revision},
            "node_uuid": str(route.node_uuid), "placement_uuid": str(route.placement_uuid),
            "fingerprint": route.fingerprint, "request_uuid": str(request_uuid),
            "body": base64.b64encode(body).decode()})
        if status in {401,403}:
            raise McpAdmissionRejected("MCP_CURRENT_EFFECT_GRANT_REQUIRED",status)
        if (status != 200 or not isinstance(result, dict) or set(result) not in ({"permit"}, {"permit", "context"})
            or not isinstance(result["permit"], str) or not 0 < len(result["permit"]) <= 8192):
            raise ValueError("Current exact module effect authority unavailable")
        context = result.get("context", "")
        if not isinstance(context, str) or len(context) > 11000:
            raise ValueError("Bounded owner invocation context required")
        if context:
            raw = base64.b64decode(context, validate=True)
            if not raw or len(raw) > 8192 or not isinstance(strict_json(raw), dict):
                raise ValueError("Exact bounded owner context required")
        return {"permit": result["permit"], "context": context}

    async def decide(self, *, bearer: str, body: bytes, module: str):
        if (module not in MODULES
            or not bearer.startswith("Bearer ") or bearer.count(" ") != 1):
            raise ValueError("Exact resource-scoped connection required")
        command = json.loads(body)
        status, result = await self.peer.call("/internal/v1/authorization/mcp-admission",
            {"bearer": bearer[7:], "module": module, "decision": command})
        # A verified peer response is required by PeerClient.call. Error
        # bodies can never expose a token or be reinterpreted as a Permit.
        return PrivateAdmissionReply(status, b'{"allowed":true}' if status == 200 and result == {"allowed": True}
            and result.get("allowed") is True else b'{}')
