"""Human Browser authority is Core-signed, project-bound and separate from agents."""

import hashlib
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

import httpx
import pytest
from bridge._node_routing import GatewayNodeRouter
from bridge.infrastructure.admission import PrivateAdmissionReply
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.applications import Starlette
from starlette.routing import Route

from bridge.thin_gateway import ThinGateway
from node_protocol.control import canonical
from node_protocol.effect import HumanEffectPermit, HumanPermitVerifier, sign_permit
from node_protocol.forward import ForwardVerifier, HumanForwardProof, TransportProof
from node_protocol.journal_codec import _decode_forward, _encode_forward
from node_protocol.module_effects import resource_id
from node_protocol.routing import NodeRoute


class NodeReply(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'


class NoAgentAdmission:
    async def decide(self, *, bearer: str, body: bytes, module: str) -> PrivateAdmissionReply:
        raise AssertionError(f"Unexpected agent admission for {module}: {bool(bearer and body)}")


def public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


@dataclass
class BrowserFixture:
    project: UUID = field(default_factory=uuid4)
    node: UUID = field(default_factory=uuid4)
    placement: UUID = field(default_factory=uuid4)
    workspace: UUID = field(default_factory=uuid4)
    core_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    gateway_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    route_calls: int = 0
    seen: list[TransportProof] = field(default_factory=list)
    body: bytes = field(
        default_factory=lambda: canonical(
            {
                "jsonrpc": "2.0",
                "id": str(uuid4()),
                "method": "tools/list",
                "params": {},
            }
        )
    )
    bearer: str = "Bearer provider-browser-fixture"
    module: Literal["web", "files", "terminal", "reverse"] = "web"
    stale_placement: bool = False

    def permit(self) -> HumanEffectPermit:
        now = int(time.time())
        return HumanEffectPermit(
            human=True,
            module=self.module,
            resource_revision=3,
            node_uuid=self.node,
            placement_uuid=self.placement,
            project_uuid=self.project,
            workspace_uuid=self.workspace,
            actor_uuid=uuid4(),
            request_uuid=UUID(json.loads(self.body)["id"]),
            fingerprint="a" * 64,
            body_digest=hashlib.sha256(self.body).hexdigest(),
            bearer_digest=hashlib.sha256(self.bearer.encode()).hexdigest(),
            arguments_digest=hashlib.sha256(canonical({})).hexdigest(),
            method="tools/list",
            tool=None,
            resource_id=resource_id(self.module, self.node, self.project, self.workspace),
            issued_at=now,
            expires_at=now + 5,
        )

    def headers(self) -> httpx.Headers:
        return httpx.Headers(
            {
                "authorization": self.bearer,
                "content-type": "application/json",
                "x-briareus-project-uuid": str(self.project),
                (
                    "x-briareus-human-web-permit"
                    if self.module == "web"
                    else "x-briareus-human-permit"
                ): sign_permit(self.permit(), self.core_key),
            }
        )

    async def resolve(self, *, project_uuid: UUID, module: str) -> NodeRoute:
        self.route_calls += 1
        assert project_uuid == self.project and module == self.module
        return NodeRoute(
            node_uuid=self.node,
            placement_uuid=uuid4() if self.stale_placement else self.placement,
            project_uuid=self.project,
            module=self.module,
            fingerprint="a" * 64,
            port=8000,
            origin="https://node.example",
            expires_at=int(time.time()) + 5,
        )

    def forward(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://node.example/internal/v1/node/mcp"
        assert "x-briareus-agent-session-uuid" not in request.headers
        assert "x-briareus-grant-revision" not in request.headers
        proof = ForwardVerifier(public_key(self.gateway_key), self.node).verify(
            request.headers["x-briareus-node-proof"],
            request.headers["x-briareus-node-signature"],
            body=request.content,
            bearer=request.headers["authorization"],
            effect=request.headers["x-briareus-node-permit"],
        )
        assert isinstance(proof, HumanForwardProof)
        wire = _encode_forward(proof)
        assert wire.human and not wire.agent_session_uuid and not wire.grant_revision
        assert _decode_forward(wire) == proof
        wire.agent_session_uuid = str(uuid4())
        with pytest.raises(ValueError, match="Mixed human and agent"):
            _decode_forward(wire)
        self.seen.append(proof)
        return httpx.Response(200, stream=NodeReply(), headers={"content-type": "application/json"})

    @asynccontextmanager
    async def client(self, *, configured: bool = True) -> AsyncIterator[httpx.AsyncClient]:
        router = GatewayNodeRouter(
            routes=self,
            signing_key=self.gateway_key,
            allowed_origins={"https://node.example"},
            human_verifier=HumanPermitVerifier(public_key(self.core_key)) if configured else None,
        )
        gateway = ThinGateway(NoAgentAdmission(), node_router=router)
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.forward)) as upstream:
            gateway._client = upstream
            app = Starlette(
                routes=[
                    Route("/hands/web/mcp", gateway.mcp, methods=["POST"]),
                    Route("/hands/files/mcp", gateway.mcp, methods=["POST"]),
                    Route("/hands/terminal/mcp", gateway.mcp, methods=["POST"]),
                    Route("/hands/reverse/mcp", gateway.mcp, methods=["POST"]),
                ]
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://gateway"
            ) as client:
                yield client


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["web", "files", "terminal", "reverse"])
async def test_human_uses_verified_project_authority_without_agent_session(
    module: Literal["web", "files", "terminal", "reverse"],
) -> None:
    fixture = BrowserFixture(module=module)
    async with fixture.client() as client:
        response = await client.post(
            f"/hands/{module}/mcp", headers=fixture.headers(), content=fixture.body
        )
    assert response.status_code == 200
    assert fixture.route_calls == 1
    assert len(fixture.seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["body", "bearer", "project", "signature", "mixed", "duplicate"])
async def test_untrusted_human_selectors_cannot_bypass_agent_admission(change: str) -> None:
    fixture = BrowserFixture()
    headers, body = fixture.headers(), fixture.body
    match change:
        case "body":
            body += b" "
        case "bearer":
            headers["authorization"] = "Bearer another-provider-token"
        case "project":
            headers["x-briareus-project-uuid"] = str(uuid4())
        case "signature":
            headers["x-briareus-human-web-permit"] = sign_permit(
                fixture.permit(), Ed25519PrivateKey.generate()
            )
        case "mixed":
            headers["x-briareus-agent-session-uuid"] = str(uuid4())
        case "duplicate":
            headers = httpx.Headers(
                [
                    *headers.multi_items(),
                    ("x-briareus-human-web-permit", headers["x-briareus-human-web-permit"]),
                ]
            )
    async with fixture.client() as client:
        response = await client.post("/hands/web/mcp", headers=headers, content=body)
    assert response.status_code in {400, 503}
    assert fixture.route_calls == 0
    assert not fixture.seen


@pytest.mark.asyncio
async def test_human_permit_cannot_follow_replaced_placement() -> None:
    fixture = BrowserFixture(stale_placement=True)
    async with fixture.client() as client:
        response = await client.post(
            "/hands/web/mcp", headers=fixture.headers(), content=fixture.body
        )
    assert response.status_code == 503
    assert fixture.route_calls == 1 and not fixture.seen


@pytest.mark.asyncio
async def test_human_permit_for_another_hand_is_rejected_before_route_lookup() -> None:
    fixture = BrowserFixture()
    async with fixture.client() as client:
        response = await client.post(
            "/hands/files/mcp", headers=fixture.headers(), content=fixture.body
        )
    assert response.status_code == 503
    assert fixture.route_calls == 0 and not fixture.seen


@pytest.mark.asyncio
async def test_missing_pinned_core_key_fails_closed() -> None:
    fixture = BrowserFixture()
    async with fixture.client(configured=False) as client:
        response = await client.post(
            "/hands/web/mcp", headers=fixture.headers(), content=fixture.body
        )
    assert response.status_code == 503
    assert fixture.route_calls == 0 and not fixture.seen
