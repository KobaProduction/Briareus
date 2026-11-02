"""Independent Authorization-to-Platform project membership service identity."""

import os
import time
from datetime import UTC, datetime, timedelta

from fastapi import Request
from fastapi.responses import JSONResponse

from projects.infrastructure.access_evidence import (
    VerifiedAccessRequest,
    request_evidence,
    sign_service_response,
)
from runtime_peer import PeerIdentity, PeerVerifier
from runtime_peer.transport import _private_key

from ._oidc_access_project_api import AccessMembershipQuery, VerifiedAccessProjectPeer


class UnixAccessProjectAuthority:
    def __init__(self, public_key_file: str, signing_key_file: str, uid: int = 1002) -> None:
        peers = [
            PeerIdentity.from_file("briareus:authorization", uid, public_key_file),
        ]
        if os.environ.get("PLATFORM_RESOURCES_VERIFY_KEY_FILE"):
            peers.append(
                PeerIdentity.from_file(
                    "briareus:resources", 1006, os.environ["PLATFORM_RESOURCES_VERIFY_KEY_FILE"]
                )
            )
        self.verifier = PeerVerifier("briareus:platform", tuple(peers))
        self.key = _private_key(signing_key_file)

    async def verify(
        self, request: Request, query: AccessMembershipQuery
    ) -> VerifiedAccessProjectPeer:
        authorization = request.headers.getlist("authorization")
        if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
            raise ValueError("Signed Authorization service request required")
        uid = request.scope.get("briareus.unix_peer_uid")
        if type(uid) is not int:
            raise ValueError("Kernel-authenticated service peer required")
        token = authorization[0][7:]
        caller = self.verifier.verify(
            token=token,
            uid=uid,
            method=request.method,
            path=request.url.path,
            body=await request.body(),
        )
        binding = request_evidence(caller, token)
        if binding.consumer == "resources" and not request.url.path.endswith("/actor-context"):
            raise ValueError("Resources may only request current actor context")
        request.scope["briareus.verified_access_request"] = binding
        # The independently verified owner snapshot remains bounded by its
        # existing 30s limit. Browser startup needs more than a 5s effect;
        # individual Hands still choose shorter leases and recheck output.
        seconds = 20 if request.url.path.endswith("/actor-context") else 5
        return VerifiedAccessProjectPeer(
            "briareus:platform",
            binding.consumer,
            query.issuer,
            query.subject,
            query.project_uuid,
            datetime.now(UTC) + timedelta(seconds=seconds),
        )

    def sign_reply(self, request: Request, reply: JSONResponse) -> JSONResponse:
        binding = request.scope.get("briareus.verified_access_request")
        if not isinstance(binding, VerifiedAccessRequest):
            raise ValueError("A verified request must bind the owner reply")
        reply.headers["x-briareus-service-proof"] = sign_service_response(
            self.key,
            binding,
            reply.status_code,
            bytes(reply.body),
            int(time.time()),
        )
        return reply
