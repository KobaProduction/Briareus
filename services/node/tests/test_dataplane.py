"""Real forwarding signatures and journal admission across both node relays."""

import base64
import hashlib
import tempfile
import time
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from journal_fixture import JournalFixture as Journal
from node_agent.dataplane import McpRelay
from node_agent.gateway_server import create_app
from node_agent.journal import OperationConflict
from starlette.applications import Starlette
from starlette.routing import Route
from test_reconciliation import fixture

from node_protocol.control import canonical
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.files import workspace_resource
from node_protocol.forward import ForwardProof, ForwardVerifier
from node_protocol.provider_context import InvocationContext, ProjectAccount
from node_protocol.runtime import rootless_budget


class Body(httpx.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.data


class DataplaneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.node, self.spec = fixture()
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.verifier = ForwardVerifier(public, self.node.id)
        self.body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        self.bearer = "Bearer real-signature-test-fixture"

    def proof(
        self,
        *,
        node_uuid: UUID | None = None,
        placement_uuid: UUID | None = None,
        project_uuid: UUID | None = None,
        protocol_version: str = "",
        mcp_session_id: str = "",
        context_digest: str = "",
        issued_at: int | None = None,
        expires_at: int | None = None,
    ) -> ForwardProof:
        now = int(time.time())
        return ForwardProof(
            node_uuid=self.node.id if node_uuid is None else node_uuid,
            placement_uuid=self.spec.id if placement_uuid is None else placement_uuid,
            project_uuid=self.spec.project_uuid if project_uuid is None else project_uuid,
            agent_session_uuid=uuid4(),
            request_uuid=uuid4(),
            grant_revision=1,
            module="files",
            fingerprint=self.spec.fingerprint,
            port=self.spec.release.port,
            body_digest=hashlib.sha256(self.body).hexdigest(),
            bearer_digest=hashlib.sha256(self.bearer.encode()).hexdigest(),
            issued_at=now if issued_at is None else issued_at,
            expires_at=now + 15 if expires_at is None else expires_at,
            protocol_version=protocol_version,
            mcp_session_id=mcp_session_id,
            context_digest=context_digest,
        )

    async def test_worker_dns_label_is_bounded_and_matches_signed_routing(self) -> None:
        proof = self.proof()
        self.assertEqual(proof.container_name, self.spec.container_name)
        self.assertLessEqual(len(proof.container_name.encode("idna")), 63)
        self.assertRegex(proof.container_name, r"^[a-z0-9-]+$")
        self.assertNotEqual(proof.container_name, self.proof(placement_uuid=uuid4()).container_name)

    def headers(self, proof: ForwardProof) -> httpx.Headers:
        return httpx.Headers(
            {
                "content-type": "application/json",
                "authorization": self.bearer,
                "x-briareus-node-proof": base64.b64encode(
                    proof.model_dump_json().encode()
                ).decode(),
                "x-briareus-node-signature": base64.b64encode(
                    self.key.sign(proof.signing_bytes())
                ).decode(),
            }
        )

    def effect(self, proof: ForwardProof, context_digest: str = "") -> str:
        now = int(time.time())
        permit = NodeEffectPermit(
            node_uuid=proof.node_uuid,
            placement_uuid=proof.placement_uuid,
            project_uuid=proof.project_uuid,
            workspace_uuid=uuid4(),
            actor_uuid=uuid4(),
            agent_session_uuid=proof.agent_session_uuid,
            request_uuid=proof.request_uuid,
            grant_revision=proof.grant_revision,
            module=proof.module,
            context_digest=context_digest,
            fingerprint=proof.fingerprint,
            body_digest=proof.body_digest,
            bearer_digest=proof.bearer_digest,
            arguments_digest=hashlib.sha256(canonical({})).hexdigest(),
            method="tools/list",
            tool=None,
            resource_id=workspace_resource(proof.node_uuid, proof.project_uuid, uuid4()),
            issued_at=now,
            expires_at=now + 5,
        )
        return sign_permit(permit, Ed25519PrivateKey.generate())

    async def test_two_relays_preserve_bytes_context_and_strip_private_response_headers(
        self,
    ) -> None:
        calls: list[httpx.Request] = []

        def hand(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200,
                stream=Body(b'event: message\ndata: {"ok":true}\n\n'),
                headers={
                    "content-type": "text/event-stream",
                    "set-cookie": "private=never-forward",
                    "location": "https://private.example",
                    "mcp-session-id": "session-opaque",
                },
            )

        node_app = create_app(
            self.verifier, client=httpx.AsyncClient(transport=httpx.MockTransport(hand))
        )
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "journal-fixture")
            journal.seed_applied(self.spec, "a" * 64)

            async def admit(proof: ForwardProof, gateway_signature: str) -> str:
                try:
                    (await journal.admit_forward(proof, gateway_signature))
                except OperationConflict:
                    raise ValueError("Placement unavailable") from None
                return "http://node/internal/v1/node/mcp"

            outer = McpRelay(
                verifier=self.verifier,
                admit=admit,
                upstream_socket=True,
                client=httpx.AsyncClient(transport=httpx.ASGITransport(node_app)),
            )
            app = Starlette(
                routes=[Route("/internal/v1/node/mcp", outer.forward, methods=["POST"])]
            )
            proof = self.proof(protocol_version="2025-03-26", mcp_session_id="original-session")
            effect = self.effect(proof)
            proof = proof.model_copy(
                update={"effect_digest": hashlib.sha256(effect.encode()).hexdigest()}
            )
            headers = {**self.headers(proof), "x-briareus-node-permit": effect}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://controller"
            ) as client:
                tampered = await client.post(
                    "/internal/v1/node/mcp",
                    content=self.body,
                    headers={**headers, "x-briareus-node-permit": "substituted"},
                )
                self.assertEqual(tampered.status_code, 403)
                first = await client.post(
                    "/internal/v1/node/mcp", content=self.body, headers=headers
                )
                self.assertEqual(first.status_code, 200)
                self.assertIn(b"event: message", first.content)
                self.assertNotIn("set-cookie", first.headers)
                self.assertNotIn("location", first.headers)
                self.assertEqual(first.headers["mcp-session-id"], "session-opaque")
                again = await client.post(
                    "/internal/v1/node/mcp", content=self.body, headers=headers
                )
                self.assertEqual(again.status_code, 409)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].content, self.body)
            self.assertEqual(str(calls[0].url), f"http://{self.spec.container_name}:8000/mcp")
            self.assertEqual(calls[0].headers["authorization"], self.bearer)
            self.assertEqual(calls[0].headers["x-briareus-node-permit"], effect)
            self.assertEqual(
                calls[0].headers["x-briareus-project-uuid"], str(self.spec.project_uuid)
            )
            self.assertEqual(calls[0].headers["mcp-session-id"], "original-session")
            self.assertNotIn("x-briareus-node-proof", calls[0].headers)
            await outer.close()
            await node_app.state.relay.close()
            (await journal.close())
            journal = Journal(Path(folder) / "journal-fixture")
            with self.assertRaises(OperationConflict):
                (await journal.admit_forward(proof))
            with self.assertRaises(OperationConflict):
                (await journal.admit_forward(self.proof(project_uuid=uuid4())))
            updating = uuid4()
            (await journal.reserve(updating, 1, self.spec))
            with self.assertRaises(OperationConflict):
                (await journal.admit_forward(self.proof()))
            (await journal.phase(updating, "failed", error="ROLLBACK_FAILED"))
            with self.assertRaises(OperationConflict):
                (await journal.admit_forward(self.proof()))
            (await journal.close())

    async def test_private_context_is_bound_to_both_proof_and_effect_and_only_forwarded_server_side(
        self,
    ) -> None:
        calls: list[httpx.Request] = []

        def hand(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200,
                stream=Body(b'{"ok":true}'),
                headers={
                    "content-type": "application/json",
                    "x-briareus-invocation-context": "never-return-this",
                },
            )

        app = create_app(
            self.verifier, client=httpx.AsyncClient(transport=httpx.MockTransport(hand))
        )
        raw_context = (
            InvocationContext(
                accounts=(
                    ProjectAccount(
                        id=uuid4(),
                        alias="fixture",
                        provider="github",
                        auth_type="token",
                        base_url="https://api.github.com",
                        external_id=None,
                        ca_cert_pem=None,
                        created_at="2026-10-28T00:00:00Z",
                        updated_at="2026-10-28T00:00:00Z",
                        credential="test-only-server-credential",
                    ),
                )
            )
            .model_dump_json()
            .encode()
        )
        context = base64.b64encode(raw_context).decode()
        digest = hashlib.sha256(raw_context).hexdigest()
        proof = self.proof(context_digest=digest)
        effect = self.effect(proof, digest)
        proof = proof.model_copy(
            update={"effect_digest": hashlib.sha256(effect.encode()).hexdigest()}
        )
        headers = {
            **self.headers(proof),
            "x-briareus-node-permit": effect,
            "x-briareus-invocation-context": context,
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://node"
        ) as client:
            for changed in (
                {"x-briareus-invocation-context": base64.b64encode(b"{}").decode()},
                {"x-briareus-invocation-context": ""},
            ):
                self.assertEqual(
                    (
                        await client.post(
                            "/internal/v1/node/mcp",
                            content=self.body,
                            headers={**headers, **changed},
                        )
                    ).status_code,
                    403,
                )
            mismatched_effect = self.effect(proof, hashlib.sha256(b"{}").hexdigest())
            mismatch = proof.model_copy(
                update={"effect_digest": hashlib.sha256(mismatched_effect.encode()).hexdigest()}
            )
            self.assertEqual(
                (
                    await client.post(
                        "/internal/v1/node/mcp",
                        content=self.body,
                        headers={
                            **self.headers(mismatch),
                            "x-briareus-node-permit": mismatched_effect,
                            "x-briareus-invocation-context": context,
                        },
                    )
                ).status_code,
                403,
            )
            self.assertEqual(calls, [])
            response = await client.post(
                "/internal/v1/node/mcp", content=self.body, headers=headers
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("x-briareus-invocation-context", response.headers)
            self.assertEqual(calls[0].headers["x-briareus-invocation-context"], context)
        await app.state.relay.close()

    async def test_proof_tamper_and_hand_denial_never_become_permit(self) -> None:
        calls: list[httpx.Request] = []

        def hand(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                403,
                stream=Body(b'{"code":"HAND_EFFECT_DENIED"}'),
                headers={"content-type": "application/json"},
            )

        app = create_app(
            self.verifier, client=httpx.AsyncClient(transport=httpx.MockTransport(hand))
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://node"
        ) as client:
            proof = self.proof()
            for body, headers in [
                (self.body + b" ", self.headers(proof)),
                (self.body, {**self.headers(proof), "authorization": "Bearer other"}),
                (self.body, self.headers(self.proof(node_uuid=uuid4()))),
                (self.body, self.headers(self.proof(issued_at=1, expires_at=10))),
            ]:
                reply = await client.post("/internal/v1/node/mcp", content=body, headers=headers)
                self.assertEqual(reply.status_code, 403)
            self.assertEqual(calls, [])
            denied = await client.post(
                "/internal/v1/node/mcp", content=self.body, headers=self.headers(self.proof())
            )
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json(), {"code": "HAND_EFFECT_DENIED"})
        await app.state.relay.close()

    def test_gateway_is_accounted_inside_rootless_budget(self) -> None:
        from node_protocol import NodeBudget, ResourceLimits

        budget = NodeBudget(
            total=ResourceLimits(memory_bytes=1024 * 1024**2, cpu_millis=1000, pids=512),
            reserved=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=750, pids=192),
        )
        self.assertEqual(rootless_budget(budget).memory_bytes, 768 * 1024**2)
        with self.assertRaises(ValueError):
            rootless_budget(self.node.budget)
