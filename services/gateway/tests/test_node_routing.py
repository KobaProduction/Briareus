"""Node routing occurs only after the independently supplied PDP port permits."""
import time
import base64
import hashlib
import json
import unittest
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.applications import Starlette
from starlette.routing import Route

from bridge._mcp_admission import PrivateAdmissionReply
from bridge._node_routing import GatewayNodeRouter
from bridge._core_admission import CoreAdmission
from bridge.thin_gateway import ThinGateway
from node_protocol.forward import ForwardVerifier, ForwardRejected
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.control import canonical
from node_protocol.module_effects import resource_id
from node_protocol.routing import NodeRoute


class Body(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'


class NodeRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_target_is_project_bound_and_pdp_precedes_route_lookup(self):
        await self.verify_routing("files")

    async def test_terminal_uses_its_own_authority_before_node_forwarding(self):
        await self.verify_routing("terminal")

    async def test_remaining_six_modules_use_exact_authority_and_private_context(self):
        for module in ("web", "svc", "infrastructure", "reverse", "serena"):
            with self.subTest(module=module):
                await self.verify_routing(module)

    async def verify_routing(self, module):
        project, node, placement, session = uuid4(), uuid4(), uuid4(), uuid4()
        key = Ed25519PrivateKey.generate()
        verifier = ForwardVerifier(key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo), node)
        calls = []
        class Decisions:
            async def decide(self, **kwargs):
                calls.append("pdp")
                return PrivateAdmissionReply(200, b'{"allowed":true}')
        class Routes:
            async def resolve(self, **kwargs):
                calls.append("route")
                return NodeRoute(node_uuid=node, placement_uuid=placement, project_uuid=project,
                    module=module, fingerprint="a"*64, port=8000, origin="https://node.example",
                    expires_at=int(time.time())+5)
        context = base64.b64encode(canonical({"accounts":[],"policies":{}})).decode() if module in {"svc","infrastructure"} else ""
        effect_key, workspace, actor = Ed25519PrivateKey.generate(), uuid4(), uuid4()
        class Effects:
            async def authorize_module(self, *, admission, route, body, request_uuid):
                calls.append("effect")
                now = int(time.time())
                permit = NodeEffectPermit(module=module,node_uuid=node,placement_uuid=placement,
                    project_uuid=project,workspace_uuid=workspace,actor_uuid=actor,
                    agent_session_uuid=session,request_uuid=request_uuid,grant_revision=1,
                    fingerprint="a"*64,body_digest=hashlib.sha256(body).hexdigest(),
                    bearer_digest=hashlib.sha256(admission.bearer.encode()).hexdigest(),
                    arguments_digest=hashlib.sha256(canonical({})).hexdigest(),method="tools/list",tool=None,
                    context_digest=hashlib.sha256(base64.b64decode(context)).hexdigest() if context else "",
                    resource_id=resource_id(module,node,project,workspace),issued_at=now,expires_at=now+5)
                return {"permit":sign_permit(permit,effect_key),"context":context}
        def endpoint(request):
            calls.append("node")
            self.assertEqual(str(request.url), "https://node.example/internal/v1/node/mcp")
            proof = verifier.verify(request.headers["x-briareus-node-proof"],
                request.headers["x-briareus-node-signature"], body=request.content,
                bearer=request.headers["authorization"], effect=request.headers["x-briareus-node-permit"],
                context=request.headers.get("x-briareus-invocation-context", ""))
            if context:
                self.assertEqual(request.headers["x-briareus-invocation-context"], context)
                with self.assertRaises(ForwardRejected):
                    verifier.verify(request.headers["x-briareus-node-proof"],request.headers["x-briareus-node-signature"],
                        body=request.content,bearer=request.headers["authorization"],
                        effect=request.headers["x-briareus-node-permit"],context=base64.b64encode(b'{}').decode())
            else:
                self.assertNotIn("x-briareus-invocation-context",request.headers)
                self.assertNotIn("context_digest",json.loads(base64.b64decode(request.headers["x-briareus-node-proof"])))
            self.assertEqual(proof.project_uuid, project)
            self.assertEqual(proof.agent_session_uuid, session)
            self.assertEqual(proof.mcp_session_id, "opaque-session")
            return httpx.Response(200, stream=Body(), headers={"content-type":"application/json",
                "x-briareus-invocation-context":context,"x-briareus-node-permit":"private-not-for-browser"})
        gateway = ThinGateway(Decisions(), node_router=GatewayNodeRouter(routes=Routes(), signing_key=key,
            allowed_origins={"https://node.example"}, effect_authority=Effects()))
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
        app = Starlette(routes=[Route("/hands/"+module+"/mcp", gateway.mcp, methods=["POST"])])
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://gateway") as client:
                headers={"authorization":"Bearer provider-fixture", "content-type":"application/json",
                    "x-briareus-project-uuid":str(project), "x-briareus-agent-session-uuid":str(session),
                    "x-briareus-grant-revision":"1", "mcp-session-id":"opaque-session"}
                response=await client.post("/hands/"+module+"/mcp",content=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertNotIn("x-briareus-invocation-context",response.headers)
                self.assertNotIn("x-briareus-node-permit",response.headers)
                self.assertEqual(calls,["pdp","route","effect","node"])
                calls.clear()
                gateway._private_decision=None
                response=await client.post("/hands/"+module+"/mcp",content=b'{}',headers=headers)
                self.assertEqual(response.status_code,503)
                self.assertEqual(calls,[])
                self.assertEqual(gateway._slots._value,64)
                class DeniedEffect:
                    async def call(self,path,body):
                        return 403,{"code":"FILES_CURRENT_CEDAR_GRANT_REQUIRED"}
                gateway._private_decision=Decisions()
                gateway._node_router.effect_authority=CoreAdmission(DeniedEffect())
                response=await client.post("/hands/"+module+"/mcp",content=b'{}',headers=headers)
                self.assertEqual(response.status_code,403)
                self.assertEqual(calls,["pdp","route"])
                self.assertEqual(gateway._slots._value,64)
        finally:
            await gateway._client.aclose()
