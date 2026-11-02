"""Verify Core human evidence and bind it to the current Resources route."""

import base64
import hashlib
import time
from collections.abc import Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bridge.application.node_forwarding import NodeRoutes
from bridge.domain.admission import HumanAdmission
from bridge.domain.node_forwarding import NodePlacement, PreparedForward
from node_protocol.effect import HumanEffectPermit, HumanPermitVerifier
from node_protocol.forward import HumanForwardProof


class HumanForwarder:
    def __init__(
        self,
        routes: NodeRoutes,
        verifier: HumanPermitVerifier,
        signing_key: Ed25519PrivateKey,
        origins: frozenset[str],
        clock: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        self.routes, self.verifier, self.key = routes, verifier, signing_key
        self.origins, self.clock = origins, clock

    async def prepare(
        self,
        admission: HumanAdmission,
        body: bytes,
        *,
        protocol_version: str,
        mcp_session_id: str,
    ) -> PreparedForward:
        permit = self.verifier.verify(
            admission.permit,
            body=body,
            bearer=admission.bearer,
            project_uuid=admission.project_uuid,
        )
        if permit.module != admission.hand:
            raise ValueError("Human evidence is for a different Hand")
        route = await self.routes.resolve(project_uuid=admission.project_uuid, module=permit.module)
        now = self.clock()
        route.require_current(admission, self.origins, now)
        self._require_binding(route, permit, now)
        proof = self._proof(route, permit, admission.permit, protocol_version, mcp_session_id, now)
        return PreparedForward(
            route.origin + "/internal/v1/node/mcp",
            admission.permit,
            base64.b64encode(proof.canonical_bytes()).decode(),
            base64.b64encode(self.key.sign(proof.signing_bytes())).decode(),
            "",
        )

    @staticmethod
    def _require_binding(route: NodePlacement, permit: HumanEffectPermit, now: int) -> None:
        if (
            (
                route.node_uuid,
                route.placement_uuid,
                route.project_uuid,
                route.module,
                route.fingerprint,
            )
            != (
                permit.node_uuid,
                permit.placement_uuid,
                permit.project_uuid,
                permit.module,
                permit.fingerprint,
            )
            or not now < permit.expires_at <= now + 5
            or permit.context_digest
        ):
            raise ValueError("Human Web evidence does not match the current placement")

    @staticmethod
    def _proof(
        route: NodePlacement,
        permit: HumanEffectPermit,
        encoded: str,
        protocol_version: str,
        mcp_session_id: str,
        now: int,
    ) -> HumanForwardProof:
        return HumanForwardProof(
            human=True,
            module=permit.module,
            node_uuid=route.node_uuid,
            placement_uuid=route.placement_uuid,
            project_uuid=route.project_uuid,
            port=route.port,
            fingerprint=route.fingerprint,
            request_uuid=permit.request_uuid,
            body_digest=permit.body_digest,
            bearer_digest=permit.bearer_digest,
            effect_digest=hashlib.sha256(encoded.encode()).hexdigest(),
            context_digest="",
            protocol_version=protocol_version,
            mcp_session_id=mcp_session_id,
            issued_at=now,
            expires_at=min(route.expires_at, permit.expires_at),
        )
