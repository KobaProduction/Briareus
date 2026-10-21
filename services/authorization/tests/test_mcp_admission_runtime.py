"""Disposable Access DB + real JWT crypto and Cedar, with fixed provider/Platform fixtures."""
import json
import os
import time
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.requests import Request

from authorization._mcp_admission_runtime import mcp_admission_router
from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization._rauthy_jwks import RauthyKeysUnavailable
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.runtime_server import ActorContext
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase


@unittest.skipUnless(os.environ.get("MCP_AUTH_ACCEPTANCE") == "1", "Explicit disposable Access database required")
class McpAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings = OwnerDatabaseSettings(owner="access")
        if settings.postgres_host != "briareus-node-access-audit":
            raise RuntimeError("Refusing non-disposable Access database")
        self.db = PlatformDatabase(settings)
        self.actor, self.project, self.session = uuid4(), uuid4(), uuid4()
        self.member = self.actor
        self.permissions = ["use_resources"]
        self.platform_calls = 0
        self.issuer, self.audience = "https://provider-fixture.invalid/auth/v1/", "https://provider-fixture.invalid/hands/files/mcp"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="mcp-admission-fixture", alg="RS256", use="sig")
        def fetch(url, maximum):
            if url == self.issuer + ".well-known/openid-configuration":
                return {"issuer": self.issuer, "jwks_uri": self.issuer + "oidc/certs"}
            if url == self.issuer + "oidc/certs":
                return {"keys": [jwk]}
            raise AssertionError("Unexpected provider destination")
        self.issuers = {"files": TrustedRauthyIssuerKeys(issuer=self.issuer, resource_audience=self.audience,
            oauth_client_id="fixture-public-client", json_fetch=fetch)}
        async def platform(path, value):
            self.platform_calls += 1
            return 200, {"issuer": value["issuer"], "subject": value["subject"],
                "actor_uuid": str(self.member), "project_uuid": value["project_uuid"], "role": "user",
                "permissions": self.permissions, "expires_at": (datetime.now(UTC)+timedelta(seconds=15)).isoformat()}
        peer = type("PlatformFixture", (), {"call": staticmethod(platform)})()
        self.platform = peer
        self.endpoint = mcp_admission_router(platform=peer, resolve_database=lambda:self.db,
            actor_model=ActorContext, issuers=self.issuers).routes[0].endpoint
        async with self.db.transaction() as tx:
            tx.add(ProjectAgentSessionRow(session_uuid=self.session, project_id=self.project,
                created_by_principal_id=self.actor, grants={"operations":["files.read"]}, is_elevated=False,
                elevation_policy="fixed", status="active", version=1,
                created_at=datetime.now(UTC), hard_expires_at=datetime.now(UTC)+timedelta(minutes=10)))

    async def asyncTearDown(self):
        await self.db.close()

    def token(self, **updates):
        now=int(time.time())
        claims={"iss":self.issuer,"aud":self.audience,"sub":"S"*24,"iat":now,"nbf":now,
            "exp":now+60,"typ":"Bearer","azp":"fixture-public-client","jti":str(uuid4())}
        claims.update(updates)
        return jwt.encode(claims,self.key,algorithm="RS256",headers={"kid":"mcp-admission-fixture"})

    async def check(self, *, token=None, revision=1, peer="briareus:gateway", module="files"):
        value={"bearer":token or self.token(),"module":module,"decision":{"project_uuid":str(self.project),
            "agent_session_uuid":str(self.session),"expected_grant_revision":revision,"action":"mcp.connect"}}
        raw=json.dumps(value).encode()
        async def receive():
            return {"type":"http.request","body":raw,"more_body":False}
        return await self.endpoint(Request({"type":"http","method":"POST","path":"/internal/v1/authorization/mcp-admission",
            "headers":[],"briareus.service_peer":peer},receive))

    async def test_current_cedar_grant_then_revision_and_revocation(self):
        permitted=await self.check()
        self.assertEqual(permitted.status_code,200)
        self.assertEqual(json.loads(permitted.body),{"allowed":True})
        async with self.db.transaction() as tx:
            row=await tx.get(ProjectAgentSessionRow,self.session)
            row.version=2
        self.assertEqual((await self.check()).status_code,403)
        self.assertEqual((await self.check(revision=2)).status_code,200)
        async with self.db.transaction() as tx:
            row=await tx.get(ProjectAgentSessionRow,self.session)
            row.status="revoked"
            row.revoked_at=datetime.now(UTC)
        self.assertEqual((await self.check(revision=2)).status_code,403)

    async def test_signature_audience_purpose_actor_and_peer_are_independent(self):
        for token in [self.token(aud="https://other.invalid/hands/files/mcp"),self.token(typ="Id"),
                      self.token(exp=1),self.token()[:-20]+"a"*20]:
            response=await self.check(token=token)
            self.assertEqual(response.status_code,401)
            self.assertNotIn(token.encode(),response.body)
        self.assertEqual(self.platform_calls,0)
        self.assertEqual((await self.check(peer="briareus:control-panel-api")).status_code,403)
        self.member=uuid4()
        self.assertEqual((await self.check()).status_code,403)
        self.member=self.actor
        self.permissions=[]
        self.assertEqual((await self.check()).status_code,403)

    async def test_key_outage_and_unconfigured_module_fail_closed(self):
        class MissingKeys:
            async def get_verifier(self):
                raise RauthyKeysUnavailable("fixture outage")
        self.issuers["files"]=MissingKeys()
        self.assertEqual((await self.check()).status_code,503)
        self.assertEqual((await self.check(module="terminal")).status_code,503)
        self.assertEqual(self.platform_calls,0)

    async def test_node_files_effect_needs_exact_workspace_grant_and_pinned_owner_binding(self):
        await self.verify_node_workspace_effect("files")

    async def test_node_terminal_effect_needs_exact_workspace_grant_and_pinned_owner_binding(self):
        await self.verify_node_workspace_effect("terminal")

    async def test_all_additional_hands_need_exact_grants_and_correct_audiences(self):
        for module in ("web", "svc", "infrastructure", "reverse", "serena"):
            with self.subTest(module=module):
                # Reuse the isolated DB row and restore the primary JWT audience.
                self.audience = "https://provider-fixture.invalid/hands/files/mcp"
                await self.verify_node_workspace_effect(module)
                async with self.db.transaction() as tx:
                    row = await tx.get(ProjectAgentSessionRow, self.session)
                    row.status, row.revoked_at, row.is_elevated = "active", None, False

    async def verify_node_workspace_effect(self, module):
        import base64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from authorization._node_files_effect import node_workspace_effect_router
        from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
        from node_protocol.effect import EffectVerifier, NodeWorkspaceBinding
        from node_protocol.module_effects import resource_id, effect_action, RESOURCE_KINDS
        from node_protocol.catalog import ARTIFACTS
        if module != "files":
            self.audience = self.audience.replace("/files/", "/"+module+"/")
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            jwk.update(kid="mcp-admission-fixture", alg="RS256", use="sig")
            def fetch(url, maximum):
                if url == self.issuer + ".well-known/openid-configuration":
                    return {"issuer":self.issuer,"jwks_uri":self.issuer+"oidc/certs"}
                if url == self.issuer + "oidc/certs":
                    return {"keys":[jwk]}
                raise AssertionError("Unexpected provider destination")
            self.issuers[module] = TrustedRauthyIssuerKeys(issuer=self.issuer,resource_audience=self.audience,
                oauth_client_id="fixture-public-client",json_fetch=fetch)
        tool = {"files":"file_read", "terminal":"terminal_exec", "web":"browser_open", "svc":"github_accounts",
            "infrastructure":"observability_sources", "reverse":"list_projects",
            "serena":"get_symbols_overview"}[module]
        action, kind = effect_action(module, tool), RESOURCE_KINDS[module]
        async with self.db.transaction() as tx:
            row=await tx.get(ProjectAgentSessionRow,self.session)
            row.grants={"operations":[action]}
        key=Ed25519PrivateKey.generate()
        spec=Deployment(id=uuid4(),node_uuid=uuid4(),project_uuid=self.project,
            workspace=WorkspaceMount(id=uuid4()),effect_verify_key=key.public_key().public_bytes(
                serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
            release=ModuleRelease(module=module,image="registry.example/files@sha256:"+"a"*64,lifecycle="sessionful"),
            limits=ResourceLimits(**ARTIFACTS[module].default_limits))
        binding=NodeWorkspaceBinding(node_uuid=spec.node_uuid,placement_uuid=spec.id,project_uuid=self.project,resource_revision=1,
            workspace_uuid=spec.workspace.id,fingerprint=spec.fingerprint,effect_verify_key=spec.effect_verify_key,
            resource_id=resource_id(module,spec.node_uuid,self.project,spec.workspace.id),expires_at=int(time.time())+5)
        bindings={"binding":binding.model_dump(mode="json")}
        async def resource_call(path,value):
            if path == "/internal/v1/resources/node-invocation":
                self.assertEqual(value["module"], module)
                self.assertEqual(value["actor_uuid"], str(self.actor))
                return 200, {"context":{"accounts":[]}, "expires_at":bindings["binding"]["expires_at"]}
            self.assertEqual(path,"/internal/v1/resources/node-"+module+"-authority")
            return 200,bindings
        peer=type("ResourcesFixture",(),{"call":staticmethod(resource_call)})()
        # Same provider/Platform fixtures as the coarse path; actual JWT, SQL and Cedar remain in use.
        endpoint=node_workspace_effect_router(module=module,platform=self.platform,resources=peer,resolve_database=lambda:self.db,
            actor_model=ActorContext,issuers=self.issuers,signing_key=key).routes[0].endpoint
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"file_read","arguments":{"path":"fixture.txt"}}}'
        if module == "terminal":
            body=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"terminal_exec","arguments":{"workspace_id":"fixture","command":"printf fixture","timeout_seconds":1}}}'
        if module not in {"files", "terminal"}:
            body=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
                "params":{"name":tool,"arguments":{}}}).encode()
        token=self.token()
        async def check():
            raw=json.dumps({"bearer":token,"module":module,"decision":{"project_uuid":str(self.project),
                "agent_session_uuid":str(self.session),"expected_grant_revision":1,"action":"mcp.connect"},
                "node_uuid":str(spec.node_uuid),"placement_uuid":str(spec.id),"fingerprint":spec.fingerprint,
                "request_uuid":str(uuid4()),"body":base64.b64encode(body).decode()}).encode()
            async def receive():
                return {"type":"http.request","body":raw,"more_body":False}
            return await endpoint(Request({"type":"http","method":"POST","path":"/internal/v1/authorization/node-"+module+"-effect",
                "headers":[],"briareus.service_peer":"briareus:gateway"},receive))
        self.assertEqual((await check()).status_code,403)  # Broad files.read alone is insufficient.
        async with self.db.transaction() as tx:
            row=await tx.get(ProjectAgentSessionRow,self.session)
            row.grants={"operations":[action],"resources":[{"hand":module,"tool":tool,
                "action":action,"resource":{"kind":kind,"id":binding.resource_id}}]}
        if module != "files":
            # Exact scope in an ordinary session still cannot execute elevated effects.
            self.assertEqual((await check()).status_code,403)
            async with self.db.transaction() as tx:
                row=await tx.get(ProjectAgentSessionRow,self.session)
                row.is_elevated=True  # Native SQL fixture; live approval is a separate acceptance gate.
        response=await check()
        self.assertEqual(response.status_code,200,response.body)
        permit=EffectVerifier(spec).verify(json.loads(response.body)["permit"],body=body,bearer="Bearer "+token)
        self.assertEqual(permit.actor_uuid,self.actor)
        if module in {"svc", "infrastructure"}:
            import hashlib
            private = base64.b64decode(json.loads(response.body)["context"], validate=True)
            self.assertEqual(permit.context_digest, hashlib.sha256(private).hexdigest())
            self.assertEqual(json.loads(private), {"accounts":[]})
        else:
            self.assertNotIn("context", json.loads(response.body))
        bindings["binding"]["workspace_uuid"]=str(uuid4())
        self.assertEqual((await check()).status_code,503)
        bindings["binding"]=binding.model_dump(mode="json")
        async with self.db.transaction() as tx:
            row=await tx.get(ProjectAgentSessionRow,self.session)
            row.status="revoked"
            row.revoked_at=datetime.now(UTC)
        self.assertEqual((await check()).status_code,403)
