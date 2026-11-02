"""An authenticated owner denial remains nonce-bound and signature-verifiable."""

import hashlib
import unittest
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from projects._oidc_access_project_api import (
    AccessMembershipQuery,
    VerifiedAccessProjectPeer,
    oidc_access_project_router,
)
from projects.access_peer import UnixAccessProjectAuthority
from projects.domain.membership import CurrentRauthyPlatformMembership
from projects.infrastructure.access_evidence import VerifiedAccessRequest
from starlette.requests import Request


class BoundReplyAttestor(UnixAccessProjectAuthority):
    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()

    async def verify(
        self, request: Request, query: AccessMembershipQuery
    ) -> VerifiedAccessProjectPeer:
        request.scope["briareus.verified_access_request"] = VerifiedAccessRequest(
            "authorization", "owner-bound-request"
        )
        return VerifiedAccessProjectPeer(
            "briareus:platform",
            "authorization",
            query.issuer,
            query.subject,
            query.project_uuid,
            datetime.now(UTC) + timedelta(seconds=20),
        )


class MembershipSource:
    unavailable = False

    async def resolve(self, *, issuer: str, subject: str) -> CurrentRauthyPlatformMembership | None:
        del issuer, subject
        raise AssertionError("The service peer may request only an exact project")

    async def resolve_project(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> CurrentRauthyPlatformMembership | None:
        del issuer, subject, project_uuid
        if self.unavailable:
            raise RuntimeError("Owner fixture unavailable")
        return None


def request(authenticated: bool = True) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/internal/v1/platform/oidc/actor-context",
            "headers": [(b"content-type", b"application/json")]
            + ([(b"authorization", b"Bearer authenticated-fixture")] if authenticated else []),
        }
    )


class AccessPeerDenialTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_denial_and_source_outage_are_signed(self) -> None:
        attestor, source = BoundReplyAttestor(), MembershipSource()
        router = oidc_access_project_router(projection=source, attestor=attestor)
        route = next(item for item in router.routes if isinstance(item, APIRoute))
        endpoint = cast(
            Callable[[AccessMembershipQuery, Request], Awaitable[JSONResponse]], route.endpoint
        )
        query = AccessMembershipQuery(
            issuer="https://provider.example",
            subject="fixture",
            project_uuid=uuid4(),
        )
        for unavailable, status in ((False, 403), (True, 503)):
            source.unavailable = unavailable
            response = await endpoint(query, request())
            self.assertEqual(response.status_code, status)
            claims = jwt.decode(
                response.headers["x-briareus-service-proof"],
                attestor.key.public_key(),
                algorithms=["EdDSA"],
                audience="briareus:authorization",
                issuer="briareus:platform",
            )
            self.assertEqual(claims["jti"], "owner-bound-request")
            self.assertEqual(claims["status"], status)
            self.assertEqual(claims["digest"], hashlib.sha256(response.body).hexdigest())
        response = await endpoint(query, request(False))
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("x-briareus-service-proof", response.headers)

    def test_reply_without_verified_request_evidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BoundReplyAttestor().sign_reply(request(), JSONResponse({"error": "fixture"}))
