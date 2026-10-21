"""A continuation must retain current start rights, not just a poll grant."""
import base64
import json
import time
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.requests import Request

from authorization._decision_api import AuthorizedCurrentGrant
from authorization._node_files_effect import node_workspace_effect_router
from node_protocol.module_effects import resource_id


class WebPollAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_only_and_changed_revision_cannot_resume_an_effect(self):
        node, placement, project, storage, actor, session = (uuid4() for _ in range(6))
        key = Ed25519PrivateKey.generate()
        binding = dict(node_uuid=str(node), placement_uuid=str(placement), project_uuid=str(project),
            workspace_uuid=str(storage), fingerprint="a"*64, resource_revision=1,
            resource_id=resource_id("web", node, project, storage), expires_at=int(time.time())+5,
            effect_verify_key=key.public_key().public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        expiry = datetime.now(UTC)+timedelta(seconds=30)
        current = AuthorizedCurrentGrant(actor_uuid=actor, project_uuid=project,
            agent_session_uuid=session, grant_revision=7, expires_at=expiry)
        identity = (SimpleNamespace(actor_uuid=actor, expires_at=expiry), SimpleNamespace(expires_at=expiry))
        resources = SimpleNamespace(call=AsyncMock(return_value=(200,{"binding":binding})))
        router = node_workspace_effect_router(module="web", platform=object(), resources=resources,
            resolve_database=lambda:object(), actor_model=object(), issuers={"web":object()}, signing_key=key)
        body = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call", "params":{
            "name":"web_operation_poll","arguments":{"operation_id":str(uuid4())+":"+str(uuid4()),"tool":"local_browser_open"}}}).encode()
        command = {"module":"web","bearer":"fixture-not-a-provider-token-"+"x"*40,
            "decision":{"project_uuid":str(project),"agent_session_uuid":str(session),
                "action":"mcp.connect","expected_grant_revision":7},
            "node_uuid":str(node),"placement_uuid":str(placement),"request_uuid":str(uuid4()),
            "fingerprint":"a"*64,"body":base64.b64encode(body).decode()}
        for missing, expected in (("local_browser_open",403),("web_operation_start",403),("revision",403),(None,200)):
            seen = []

            async def read(decision, caller):
                self.assertEqual(caller.attested_effect_key, decision.effect_key())
                self.assertEqual((decision.hand,decision.resource.id), ("web",binding["resource_id"]))
                seen.append(decision.tool)
                if decision.tool==missing: return None
                if missing=="revision" and decision.tool=="local_browser_open": return replace(current,grant_revision=8)
                return current

            with patch("authorization._node_files_effect.current_identity", AsyncMock(return_value=identity)), \
                 patch("authorization._node_files_effect.AuthorizationDecisionReader") as reader:
                reader.return_value.current_grant = AsyncMock(side_effect=read)
                async def receive():
                    return {"type":"http.request","body":json.dumps(command).encode(),"more_body":False}
                request = Request({"type":"http","method":"POST","path":"/internal/v1/authorization/node-web-effect",
                    "headers":[],"briareus.service_peer":"briareus:gateway"},receive)
                response = await router.routes[0].endpoint(request)
                self.assertEqual(response.status_code,expected,response.body)
                self.assertEqual(seen, ["web_operation_poll","local_browser_open"] + ([] if missing in {"local_browser_open","revision"} else ["web_operation_start"]))
                if expected==200:
                    self.assertIn("permit", json.loads(response.body))


if __name__=="__main__":
    unittest.main()
