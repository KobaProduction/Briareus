"""Independent Authorization-to-Platform project membership service identity."""

import hashlib
import time
import os
from datetime import UTC, datetime, timedelta

import jwt

from fastapi import Request
from fastapi.responses import JSONResponse
from runtime_peer import PeerIdentity, PeerVerifier
from runtime_peer.transport import _LIFETIME, _TYPE, _private_key

from ._oidc_access_project_api import AccessMembershipQuery, VerifiedAccessProjectPeer


class UnixAccessProjectAuthority:
    def __init__(self, public_key_file: str, signing_key_file: str, uid: int = 1002) -> None:
        peers = [
            PeerIdentity.from_file("briareus:authorization", uid, public_key_file),
        ]
        if os.environ.get("PLATFORM_RESOURCES_VERIFY_KEY_FILE"):
            peers.append(PeerIdentity.from_file("briareus:resources", 1006,
                         os.environ["PLATFORM_RESOURCES_VERIFY_KEY_FILE"]))
        self.verifier = PeerVerifier("briareus:platform", tuple(peers))
        self.key = _private_key(signing_key_file)

    async def verify(self, request: Request, query: AccessMembershipQuery) -> VerifiedAccessProjectPeer:
        authorization = request.headers.getlist("authorization")
        if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
            raise ValueError("Signed Authorization service request required")
        caller = self.verifier.verify(token=authorization[0][7:],
                             uid=request.scope.get("briareus.unix_peer_uid"),
                             method=request.method, path=request.url.path,
                             body=await request.body())
        if caller == "briareus:resources" and not request.url.path.endswith("/actor-context"):
            raise ValueError("Resources may only request current actor context")
        request.scope["briareus.access_request_consumer"] = caller.split(":", 1)[1]
        request.scope["briareus.access_request_nonce"] = jwt.decode(
            authorization[0][7:], options={"verify_signature": False})["jti"]
        # The independently verified owner snapshot remains bounded by its
        # existing 30s limit. Browser startup needs more than a 5s effect;
        # individual Hands still choose shorter leases and recheck output.
        seconds = 20 if request.url.path.endswith("/actor-context") else 5
        return VerifiedAccessProjectPeer("briareus:platform", request.scope["briareus.access_request_consumer"], query.issuer,
                                         query.subject, query.project_uuid,
                                         datetime.now(UTC) + timedelta(seconds=seconds))

    def sign_reply(self, request: Request, reply: JSONResponse) -> JSONResponse:
        now = int(time.time())
        reply.headers["x-briareus-service-proof"] = jwt.encode(
            {"iss": "briareus:platform", "aud": "briareus:" + request.scope["briareus.access_request_consumer"],
             "iat": now, "exp": now + _LIFETIME,
             "jti": request.scope["briareus.access_request_nonce"],
             "status": reply.status_code, "digest": hashlib.sha256(reply.body).hexdigest()},
            self.key, algorithm="EdDSA", headers={"typ": _TYPE, "kid": "briareus:platform"})
        return reply
