"""Actual JWT signatures and provider contract fixtures; no live identity issuance."""
import json
import time
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient, MockTransport, Response
from pydantic import SecretStr

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_id_token import OidcIdentityRejected, VerifiedOidcIdentity
from control_panel_api._oidc_resource import PrivateOidcResourceCredential
from control_panel_api._oidc_origin_policy import RESOURCE_BROKER_CLIENT_ID, mcp_resource_audience
from control_panel_api._resource_broker import (
    GRANT,
    RFC8693_RESOURCE_KIND,
    ResourceBrokerSettings,
    ResourceCredentialUnavailable,
    ResourceTokenBroker,
)

ISSUER="https://localhost:18444/auth/v1/"
CLIENT="briareus-local-panel"
SUBJECT="A"*24


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid="broker-fixture",use="sig",alg="RS256")
        self.changes={};self.extra={};self.calls=0;self.user_status=200;self.identity_subject=SUBJECT
        self.token_status=200;self.grants=["authorization_code","refresh_token",GRANT]
        self.secret="confidential-fixture-"+"b"*40
        now=int(time.time())
        self.primary_claims={"iss":ISSUER,"sub":SUBJECT,"aud":[CLIENT,self.audience("files")],"azp":CLIENT,
            "typ":"Bearer","iat":now,"nbf":now,"exp":now+240,"jti":"primary-fixture"}
        self.primary=self.sign(self.primary_claims)
        expiry=datetime.now(UTC)+timedelta(seconds=200)
        self.identity=VerifiedOidcIdentity(ISSUER,SUBJECT,CLIENT,expiry)
        self.source=PrivateOidcResourceCredential(ISSUER,SUBJECT,CLIENT,self.audience("files"),expiry,SecretStr(self.primary))
        self.http=AsyncClient(transport=MockTransport(self.handle),follow_redirects=False)
        self.provider=RauthyOidcAdapter(issuer=ISSUER,client_id=CLIENT,http_client=self.http,
            resource_audience=self.audience("files"),cache_seconds=1)
        self.broker=ResourceTokenBroker(provider=self.provider,settings=ResourceBrokerSettings(
            client_id=RESOURCE_BROKER_CLIENT_ID,client_secret=SecretStr(self.secret)))

    async def asyncTearDown(self): await self.http.aclose()

    def audience(self,hand):return mcp_resource_audience(issuer=ISSUER,client_id=CLIENT,hand=hand)
    def sign(self,claims):return jwt.encode(claims,self.key,algorithm="RS256",headers={"kid":"broker-fixture"})

    async def handle(self,request):
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return Response(200,json={"issuer":ISSUER,"authorization_endpoint":ISSUER+"oidc/authorize",
                "token_endpoint":ISSUER+"oidc/token","jwks_uri":ISSUER+"oidc/certs",
                "userinfo_endpoint":ISSUER+"oidc/userinfo","code_challenge_methods_supported":["S256"],
                "response_types_supported":["code"],"grant_types_supported":self.grants})
        if request.url.path.endswith("/oidc/certs"):return Response(200,json={"keys":[self.jwk]})
        if request.url.path.endswith("/oidc/userinfo"):
            self.assertEqual(request.headers["authorization"],"Bearer "+self.primary)
            return Response(self.user_status,json={"sub":self.identity_subject})
        if request.url.path.endswith("/oidc/token"):
            self.calls+=1
            form=parse_qs(request.content.decode())
            self.assertEqual(form["grant_type"],[GRANT])
            self.assertEqual(form["client_id"],[RESOURCE_BROKER_CLIENT_ID])
            self.assertEqual(form["client_secret"],[self.secret])
            self.assertEqual(form["subject_token"],[self.primary])
            self.assertEqual(form["subject_token_type"],[RFC8693_RESOURCE_KIND])
            self.assertEqual(form["requested_token_type"],[RFC8693_RESOURCE_KIND])
            self.assertNotIn("origin",request.headers)
            now=int(time.time())
            claims={"iss":ISSUER,"sub":SUBJECT,"aud":[RESOURCE_BROKER_CLIENT_ID,form["resource"][0]],
                "azp":RESOURCE_BROKER_CLIENT_ID,"typ":"Bearer","iat":now,"nbf":now,"exp":now+90,"jti":"derived-fixture"}
            claims.update(self.changes)
            return Response(self.token_status,json={"access_token":self.sign(claims),"token_type":"Bearer",
                "expires_in":90,"scope":"openid profile email",**self.extra})
        raise AssertionError("Unapproved provider destination")

    async def test_each_module_gets_separate_signed_audience_and_original_identity(self):
        for hand in ["terminal","web","svc","infrastructure","reverse","serena"]:
            result=await self.broker.exchange(source=self.source,identity=self.identity,hand=hand)
            self.assertEqual(result.subject,SUBJECT)
            self.assertEqual(result.client_id,CLIENT)  # Escrow belongs to original browser client.
            self.assertEqual(result.audience,self.audience(hand))
            self.assertLessEqual(result.expires_at,self.source.expires_at)
            claims=jwt.decode(result.bearer.get_secret_value(),self.key.public_key(),algorithms=["RS256"],audience=self.audience(hand))
            self.assertEqual(set(claims["aud"]),{RESOURCE_BROKER_CLIENT_ID,self.audience(hand)})

    async def test_source_identity_and_unknown_targets_fail_before_exchange(self):
        for source in [replace(self.source,subject="B"*24),replace(self.source,audience=self.audience("terminal")),
            replace(self.source,expires_at=datetime.now(UTC)-timedelta(seconds=1)),
            replace(self.source,bearer=SecretStr(self.sign({**self.primary_claims,"sub":"B"*24})))]:
            with self.assertRaises(OidcIdentityRejected):
                await self.broker.exchange(source=source,identity=self.identity,hand="terminal")
        with self.assertRaises(ValueError):
            await self.broker.exchange(source=self.source,identity=self.identity,hand="https://foreign.invalid")
        self.assertEqual(self.calls,0)

    async def test_subject_client_extra_audience_lifetime_and_delegation_rejected(self):
        for changes in [{"sub":"B"*24},{"azp":CLIENT},{"aud":[RESOURCE_BROKER_CLIENT_ID,self.audience("files")]},
            {"aud":[RESOURCE_BROKER_CLIENT_ID,self.audience("terminal"),self.audience("files")]},
            {"exp":int(time.time())+600},{"act":{"sub":"other"}},{"cnf":{"jkt":"proof"}}]:
            self.changes=changes
            with self.assertRaises(OidcIdentityRejected):
                await self.broker.exchange(source=self.source,identity=self.identity,hand="terminal")

    async def test_provider_revocation_and_missing_exchange_fail_closed_without_secret_errors(self):
        self.grants=[]
        with self.assertRaises(ResourceCredentialUnavailable):
            await self.broker.exchange(source=self.source,identity=self.identity,hand="terminal")
        self.grants=[GRANT]
        self.provider=RauthyOidcAdapter(issuer=ISSUER,client_id=CLIENT,http_client=self.http,resource_audience=self.audience("files"))
        self.broker=ResourceTokenBroker(provider=self.provider,settings=self.broker.settings)
        self.user_status=401
        with self.assertRaises(OidcIdentityRejected):
            await self.broker.exchange(source=self.source,identity=self.identity,hand="terminal")
        self.assertEqual(self.calls,0)
        self.user_status=200;self.token_status=400
        with self.assertRaises(ResourceCredentialUnavailable) as denied:
            await self.broker.exchange(source=self.source,identity=self.identity,hand="terminal")
        self.assertNotIn(self.secret,str(denied.exception));self.assertNotIn(self.primary,str(denied.exception))
        for extra in [{"refresh_token":"must-not-be-returned"},{"id_token":"must-not-authenticate-a-user"}]:
            self.extra=extra;self.token_status=200
            with self.assertRaises(ResourceCredentialUnavailable):
                await self.broker.exchange(source=self.source,identity=self.identity,hand="terminal")
