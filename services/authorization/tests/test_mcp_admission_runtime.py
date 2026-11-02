"""Disposable Access DB + real JWT crypto and Cedar, with fixed provider/Platform fixtures."""

from __future__ import annotations

import base64
import json
import os
import time
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.types import Message

from authorization._mcp_admission_runtime import McpAdmissionController
from authorization._node_files_effect import WorkspaceEffectController
from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization._rauthy_jwks import RauthyKeysUnavailable
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.domain.resource_scopes import HandName
from authorization.domain.sessions import SessionResourceGrant
from authorization.infrastructure.session_grant_storage import StoredSessionPermissions
from authorization.presentation.runtime_protocol import ActorContext
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from node_protocol.effect import NodeWorkspaceBinding, NodeWorkspaceReply
from node_protocol.provider_context import InvocationContext, InvocationLease
from runtime_peer import PeerClient, VerifiedOwnerReply
from runtime_peer.oidc_wire import IssuerDiscovery, IssuerSigningKeys


class AdmissionPlatform(PeerClient):
    def __init__(self, owner: McpAdmissionTests) -> None:
        self.test = owner

    async def call[ReplyT](
        self, path: str, payload: dict[str, object], *, decode: Callable[[int, object], ReplyT]
    ) -> VerifiedOwnerReply[ReplyT]:
        self.test.assertEqual(path, "/internal/v1/platform/oidc/actor-context")
        self.test.assertEqual(payload["project_uuid"], str(self.test.project))
        self.test.platform_calls += 1
        actor = ActorContext(
            issuer=self.test.issuer,
            subject="S" * 24,
            actor_uuid=self.test.member,
            project_uuid=self.test.project,
            role="user",
            permissions=self.test.permissions,
            expires_at=datetime.now(UTC) + timedelta(seconds=15),
        )
        return VerifiedOwnerReply(200, decode(200, actor.model_dump(mode="json")))


class AdmissionResources(PeerClient):
    def __init__(
        self, owner: McpAdmissionTests, module: str, binding: NodeWorkspaceBinding
    ) -> None:
        self.test, self.module, self.binding = owner, module, binding

    async def call[ReplyT](
        self, path: str, payload: dict[str, object], *, decode: Callable[[int, object], ReplyT]
    ) -> VerifiedOwnerReply[ReplyT]:
        if path == "/internal/v1/resources/node-invocation":
            self.test.assertEqual(payload["module"], self.module)
            self.test.assertEqual(payload["actor_uuid"], str(self.test.actor))
            lease = InvocationLease(
                context=InvocationContext(accounts=()), expires_at=self.binding.expires_at
            )
            return VerifiedOwnerReply(
                200, decode(200, lease.model_dump(mode="json", exclude_unset=True))
            )
        self.test.assertEqual(path, "/internal/v1/resources/node-" + self.module + "-authority")
        return VerifiedOwnerReply(
            200, decode(200, NodeWorkspaceReply(binding=self.binding).model_dump(mode="json"))
        )


class AdmissionIssuers:
    def __init__(self) -> None:
        self.entries: dict[str, TrustedRauthyIssuerKeys] = {}

    def get(self, module: str) -> TrustedRauthyIssuerKeys | None:
        return self.entries.get(module)


@unittest.skipUnless(
    os.environ.get("MCP_AUTH_ACCEPTANCE") == "1", "Explicit disposable Access database required"
)
class McpAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = OwnerDatabaseSettings(owner="access")
        if settings.postgres_host != "briareus-node-access-audit":
            raise RuntimeError("Refusing non-disposable Access database")
        self.db = PlatformDatabase(settings)
        self.actor, self.project, self.session = uuid4(), uuid4(), uuid4()
        self.member = self.actor
        self.permissions: tuple[Literal["use_resources", "approve_agent_session"], ...] = (
            "use_resources",
        )
        self.platform_calls = 0
        self.issuer, self.audience = (
            "https://provider-fixture.invalid/auth/v1/",
            "https://provider-fixture.invalid/hands/files/mcp",
        )
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="mcp-admission-fixture", alg="RS256", use="sig")
        self.jwks = IssuerSigningKeys.model_validate({"keys": [jwk]})
        self.issuers = AdmissionIssuers()
        self.issuers.entries["files"] = self.make_issuer_keys()
        self.platform = AdmissionPlatform(self)
        self.controller = McpAdmissionController(
            platform=self.platform,
            resolve_database=lambda: self.db,
            actor_model=ActorContext,
            issuers=self.issuers,
        )
        async with self.db.transaction() as tx:
            tx.add(
                ProjectAgentSessionRow(
                    session_uuid=self.session,
                    project_id=self.project,
                    created_by_principal_id=self.actor,
                    grants=StoredSessionPermissions(("files.read",)),
                    is_elevated=False,
                    elevation_policy="fixed",
                    status="active",
                    version=1,
                    created_at=datetime.now(UTC),
                    hard_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )

    def make_issuer_keys(self) -> TrustedRauthyIssuerKeys:
        def fetch(url: str, maximum: int) -> bytes:
            if url == self.issuer + ".well-known/openid-configuration":
                raw = (
                    IssuerDiscovery(issuer=self.issuer, jwks_uri=self.issuer + "oidc/certs")
                    .model_dump_json()
                    .encode()
                )
            elif url == self.issuer + "oidc/certs":
                raw = self.jwks.model_dump_json().encode()
            else:
                raise AssertionError("Unexpected provider destination")
            if len(raw) > maximum:
                raise AssertionError("Fixture issuer document exceeds request bound")
            return raw

        return TrustedRauthyIssuerKeys(
            issuer=self.issuer,
            resource_audience=self.audience,
            oauth_client_id="fixture-public-client",
            json_fetch=fetch,
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()

    def token(self, *, aud: str | None = None, typ: str = "Bearer", exp: int | None = None) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.audience if aud is None else aud,
            "sub": "S" * 24,
            "iat": now,
            "nbf": now,
            "exp": now + 60 if exp is None else exp,
            "typ": typ,
            "azp": "fixture-public-client",
            "jti": str(uuid4()),
        }
        return jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": "mcp-admission-fixture"}
        )

    async def check(
        self,
        *,
        token: str | None = None,
        revision: int = 1,
        peer: str = "briareus:gateway",
        module: str = "files",
    ) -> JSONResponse:
        value = {
            "bearer": token or self.token(),
            "module": module,
            "decision": {
                "project_uuid": str(self.project),
                "agent_session_uuid": str(self.session),
                "expected_grant_revision": revision,
                "action": "mcp.connect",
            },
        }
        raw = json.dumps(value).encode()

        async def receive() -> Message:
            return {"type": "http.request", "body": raw, "more_body": False}

        return await self.controller.admission(
            Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/internal/v1/authorization/mcp-admission",
                    "headers": [],
                    "briareus.service_peer": peer,
                },
                receive,
            )
        )

    async def test_current_cedar_grant_then_revision_and_revocation(self) -> None:
        permitted = await self.check()
        self.assertEqual(permitted.status_code, 200)
        self.assertEqual(json.loads(bytes(permitted.body)), {"allowed": True})
        async with self.db.transaction() as tx:
            row = await tx.get(ProjectAgentSessionRow, self.session)
            assert row is not None
            row.version = 2
        self.assertEqual((await self.check()).status_code, 403)
        self.assertEqual((await self.check(revision=2)).status_code, 200)
        async with self.db.transaction() as tx:
            row = await tx.get(ProjectAgentSessionRow, self.session)
            assert row is not None
            row.status = "revoked"
            row.revoked_at = datetime.now(UTC)
        self.assertEqual((await self.check(revision=2)).status_code, 403)

    async def test_signature_audience_purpose_actor_and_peer_are_independent(self) -> None:
        for token in [
            self.token(aud="https://other.invalid/hands/files/mcp"),
            self.token(typ="Id"),
            self.token(exp=1),
            self.token()[:-20] + "a" * 20,
        ]:
            response = await self.check(token=token)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn(token.encode(), bytes(response.body))
        self.assertEqual(self.platform_calls, 0)
        self.assertEqual((await self.check(peer="briareus:control-panel-api")).status_code, 403)
        self.member = uuid4()
        self.assertEqual((await self.check()).status_code, 403)
        self.member = self.actor
        self.permissions = ()
        self.assertEqual((await self.check()).status_code, 403)

    async def test_key_outage_and_unconfigured_module_fail_closed(self) -> None:
        keys = self.issuers.get("files")
        assert keys is not None
        with patch.object(
            keys, "get_verifier", AsyncMock(side_effect=RauthyKeysUnavailable("fixture outage"))
        ):
            self.assertEqual((await self.check()).status_code, 503)
        self.assertEqual((await self.check(module="terminal")).status_code, 503)
        self.assertEqual(self.platform_calls, 0)

    async def test_node_files_effect_needs_exact_workspace_grant_and_pinned_owner_binding(
        self,
    ) -> None:
        await self.verify_node_workspace_effect("files")

    async def test_node_terminal_effect_needs_exact_workspace_grant_and_pinned_owner_binding(
        self,
    ) -> None:
        await self.verify_node_workspace_effect("terminal")

    async def test_all_additional_hands_need_exact_grants_and_correct_audiences(self) -> None:
        modules: tuple[HandName, ...] = ("web", "svc", "infrastructure", "reverse", "serena")
        for module in modules:
            with self.subTest(module=module):
                # Reuse the isolated DB row and restore the primary JWT audience.
                self.audience = "https://provider-fixture.invalid/hands/files/mcp"
                await self.verify_node_workspace_effect(module)
                async with self.db.transaction() as tx:
                    row = await tx.get(ProjectAgentSessionRow, self.session)
                    assert row is not None
                    row.status, row.revoked_at, row.is_elevated = "active", None, False

    async def verify_node_workspace_effect(self, module: HandName) -> None:
        from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
        from node_protocol.catalog import ARTIFACTS
        from node_protocol.effect import EffectVerifier, NodeWorkspaceBinding
        from node_protocol.module_effects import RESOURCE_KINDS, effect_action, resource_id

        if module != "files":
            self.audience = self.audience.replace("/files/", "/" + module + "/")
            self.issuers.entries[module] = self.make_issuer_keys()
        tool = {
            "files": "file_read",
            "terminal": "terminal_exec",
            "web": "browser_open",
            "svc": "github_accounts",
            "infrastructure": "observability_sources",
            "reverse": "list_projects",
            "serena": "get_symbols_overview",
        }[module]
        action, kind = effect_action(module, tool), RESOURCE_KINDS[module]
        async with self.db.transaction() as tx:
            row = await tx.get(ProjectAgentSessionRow, self.session)
            assert row is not None
            row.grants = StoredSessionPermissions((action,))
        key = Ed25519PrivateKey.generate()
        limits = ARTIFACTS[module].default_limits
        spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=self.project,
            workspace=WorkspaceMount(id=uuid4()),
            effect_verify_key=key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
            release=ModuleRelease(
                module=module,
                image="registry.example/files@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(
                memory_bytes=limits.memory_bytes, cpu_millis=limits.cpu_millis, pids=limits.pids
            ),
        )
        assert spec.workspace is not None and spec.effect_verify_key is not None
        binding = NodeWorkspaceBinding(
            node_uuid=spec.node_uuid,
            placement_uuid=spec.id,
            project_uuid=self.project,
            resource_revision=1,
            workspace_uuid=spec.workspace.id,
            fingerprint=spec.fingerprint,
            effect_verify_key=spec.effect_verify_key,
            resource_id=resource_id(module, spec.node_uuid, self.project, spec.workspace.id),
            expires_at=int(time.time()) + 5,
        )
        peer = AdmissionResources(self, module, binding)
        # Same provider/Platform fixtures as the coarse path; actual JWT, SQL and Cedar remain in use.
        controller = WorkspaceEffectController(
            module=module,
            platform=self.platform,
            resources=peer,
            resolve_database=lambda: self.db,
            actor_model=ActorContext,
            issuers=self.issuers,
            signing_key=key,
        )
        body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"file_read","arguments":{"path":"fixture.txt"}}}'
        if module == "terminal":
            body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"terminal_exec","arguments":{"workspace_id":"fixture","command":"printf fixture","timeout_seconds":1}}}'
        if module not in {"files", "terminal"}:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": {}},
                }
            ).encode()
        token = self.token()

        async def check() -> JSONResponse:
            raw = json.dumps(
                {
                    "bearer": token,
                    "module": module,
                    "decision": {
                        "project_uuid": str(self.project),
                        "agent_session_uuid": str(self.session),
                        "expected_grant_revision": 1,
                        "action": "mcp.connect",
                    },
                    "node_uuid": str(spec.node_uuid),
                    "placement_uuid": str(spec.id),
                    "fingerprint": spec.fingerprint,
                    "request_uuid": str(uuid4()),
                    "body": base64.b64encode(body).decode(),
                }
            ).encode()

            async def receive() -> Message:
                return {"type": "http.request", "body": raw, "more_body": False}

            return await controller.authorize(
                Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": "/internal/v1/authorization/node-" + module + "-effect",
                        "headers": [],
                        "briareus.service_peer": "briareus:gateway",
                    },
                    receive,
                )
            )

        self.assertEqual(
            (await check()).status_code, 403
        )  # Broad files.read alone is insufficient.
        async with self.db.transaction() as tx:
            row = await tx.get(ProjectAgentSessionRow, self.session)
            assert row is not None
            row.grants = StoredSessionPermissions(
                (action,), (SessionResourceGrant(module, tool, action, kind, binding.resource_id),)
            )
        if module != "files":
            # Exact scope in an ordinary session still cannot execute elevated effects.
            self.assertEqual((await check()).status_code, 403)
            async with self.db.transaction() as tx:
                row = await tx.get(ProjectAgentSessionRow, self.session)
                assert row is not None
                row.is_elevated = (
                    True  # Native SQL fixture; live approval is a separate acceptance gate.
                )
        response = await check()
        self.assertEqual(response.status_code, 200, response.body)
        permit = EffectVerifier(spec).verify(
            json.loads(bytes(response.body))["permit"], body=body, bearer="Bearer " + token
        )
        self.assertEqual(permit.actor_uuid, self.actor)
        if module in {"svc", "infrastructure"}:
            import hashlib

            private = base64.b64decode(json.loads(bytes(response.body))["context"], validate=True)
            self.assertEqual(permit.context_digest, hashlib.sha256(private).hexdigest())
            self.assertEqual(json.loads(private), {"accounts": []})
        else:
            self.assertNotIn("context", json.loads(bytes(response.body)))
        peer.binding = binding.model_copy(update={"workspace_uuid": uuid4()})
        self.assertEqual((await check()).status_code, 503)
        peer.binding = binding
        async with self.db.transaction() as tx:
            row = await tx.get(ProjectAgentSessionRow, self.session)
            assert row is not None
            row.status = "revoked"
            row.revoked_at = datetime.now(UTC)
        self.assertEqual((await check()).status_code, 403)
