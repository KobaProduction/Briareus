"""A current non-membership denial must remain verifiable by the calling owner."""
import hashlib
import unittest
from datetime import UTC,datetime,timedelta
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.requests import Request
from projects.access_peer import UnixAccessProjectAuthority
from projects._oidc_access_project_api import oidc_access_project_router,VerifiedAccessProjectPeer,AccessMembershipQuery


class AccessPeerDenialTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_denial_and_source_outage_are_signed(self):
        class Attestor:
            key=Ed25519PrivateKey.generate()
            sign_reply=UnixAccessProjectAuthority.sign_reply
            async def verify(self,request,query):
                request.scope['briareus.access_request_consumer']='authorization'
                request.scope['briareus.access_request_nonce']='owner-bound-request'
                return VerifiedAccessProjectPeer('briareus:platform','authorization',query.issuer,
                    query.subject,query.project_uuid,datetime.now(UTC)+timedelta(seconds=20))
        class Source:
            unavailable=False
            async def resolve_project(self,**query):
                if self.unavailable:raise RuntimeError('Owner fixture unavailable')
                return None
        attestor,source=Attestor(),Source()
        endpoint=oidc_access_project_router(projection=source,attestor=attestor).routes[0].endpoint
        body={'issuer':'https://provider.example','subject':'fixture','project_uuid':str(uuid4())}
        def request(auth=True):
            return Request({'type':'http','method':'POST','path':'/internal/v1/platform/oidc/actor-context',
                'headers':[(b'content-type',b'application/json')]+([(b'authorization',b'Bearer authenticated-fixture')] if auth else [])})
        query=AccessMembershipQuery.model_validate(body)
        for unavailable,status in [(False,403),(True,503)]:
            source.unavailable=unavailable
            response=await endpoint(query,request())
            self.assertEqual(response.status_code,status)
            claims=jwt.decode(response.headers['x-briareus-service-proof'],attestor.key.public_key(),
                algorithms=['EdDSA'],audience='briareus:authorization',issuer='briareus:platform')
            self.assertEqual(claims['jti'],'owner-bound-request')
            self.assertEqual(claims['status'],status)
            self.assertEqual(claims['digest'],hashlib.sha256(response.body).hexdigest())
        response=await endpoint(query,request(False))
        self.assertEqual(response.status_code,401)
        self.assertNotIn('x-briareus-service-proof',response.headers)
