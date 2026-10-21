"""Real disposable Valkey CAS/logout races; broker output is an explicit fixture."""
import asyncio
import json
import os
import unittest
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace

from pydantic import SecretStr
from valkey.asyncio import Valkey

from control_panel_api._oidc_browser import OidcBrowserSessionStore
from control_panel_api._oidc_id_token import VerifiedOidcIdentity
from control_panel_api._oidc_origin_policy import mcp_resource_audience
from control_panel_api._oidc_resource import PrivateOidcResourceCredential
from control_panel_api._resource_escrow import SessionResourceCredentials
from control_panel_api._resource_broker import ResourceCredentialUnavailable


@unittest.skipUnless(os.environ.get("RESOURCE_ESCROW_ACCEPTANCE")=="1","Explicit disposable Valkey required")
class EscrowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if os.environ.get("ESCROW_AUDIT_HOST")!="briareus-resource-escrow-audit":
            raise RuntimeError("Refusing non-disposable Valkey")
        self.client=Valkey(host=os.environ["ESCROW_AUDIT_HOST"],password=os.environ["ESCROW_AUDIT_PASSWORD"],decode_responses=True)
        self.store=OidcBrowserSessionStore(password=SecretStr(os.environ["ESCROW_AUDIT_PASSWORD"]),client=self.client)
        expiry=datetime.now(UTC)+timedelta(seconds=120)
        self.identity=VerifiedOidcIdentity("https://localhost:18444/auth/v1/","A"*24,"briareus-local-panel",expiry)
        self.provider=SimpleNamespace(issuer=self.identity.issuer.rstrip("/"),client_id=self.identity.client_id)
        self.source=PrivateOidcResourceCredential(self.identity.issuer,self.identity.subject,self.identity.client_id,
            self.audience("files"),expiry,SecretStr("primary-fixture-"+"x"*100))
        self.ticket,_=await self.store.create_session(self.identity,resource=self.source)
        owner=self
        class Broker:
            calls=0
            gate=None
            started=asyncio.Event()
            bad_subject=False
            size=120
            async def exchange(self,*,source,identity,hand):
                self.calls+=1;self.started.set()
                if self.gate is not None: await self.gate.wait()
                return PrivateOidcResourceCredential(identity.issuer,"B"*24 if self.bad_subject else identity.subject,
                    identity.client_id,owner.audience(hand),datetime.now(UTC)+timedelta(seconds=60),
                    SecretStr(("derived-fixture-"+hand+"-").ljust(self.size,"y")))
        self.broker=Broker()
        self.resolver=SessionResourceCredentials(sessions=self.store,provider=self.provider,broker=self.broker)
        self.key=self.store._key("session",self.ticket)

    async def asyncTearDown(self):
        await self.store.delete_session(self.ticket)
        await self.client.aclose()

    def audience(self,hand):return mcp_resource_audience(issuer=self.identity.issuer,client_id=self.identity.client_id,hand=hand)

    async def test_cache_reuse_preserves_primary_and_record_ttl(self):
        before=await self.client.pttl(self.key)
        first=await self.resolver.resolve(self.ticket,"terminal")
        second=await self.resolver.resolve(self.ticket,"terminal")
        self.assertEqual(first,second);self.assertEqual(self.broker.calls,1)
        self.assertEqual((await self.resolver.resolve(self.ticket,"files")).bearer,self.source.bearer)
        raw=json.loads(await self.client.get(self.key))
        self.assertEqual(raw["resource"]["bearer"],self.source.bearer.get_secret_value())
        self.assertEqual(set(raw["mcp_resources"]),{self.audience("terminal")})
        self.assertLessEqual(await self.client.pttl(self.key),before)
        await self.store.delete_session(self.ticket)
        self.assertIsNone(await self.resolver.resolve(self.ticket,"terminal"))

    async def test_logout_during_exchange_cannot_recreate_session_or_release_token(self):
        self.broker.gate=asyncio.Event()
        task=asyncio.create_task(self.resolver.resolve(self.ticket,"terminal"))
        await self.broker.started.wait()
        await self.store.delete_session(self.ticket)
        self.broker.gate.set()
        self.assertIsNone(await task)
        self.assertIsNone(await self.client.get(self.key))

    async def test_primary_rotation_during_exchange_discards_stale_derived_token(self):
        self.broker.gate=asyncio.Event()
        task=asyncio.create_task(self.resolver.resolve(self.ticket,"terminal"))
        await self.broker.started.wait()
        raw=json.loads(await self.client.get(self.key));raw["resource"]["bearer"]="rotated-primary-"+"z"*100
        await self.client.set(self.key,json.dumps(raw),keepttl=True)
        self.broker.gate.set()
        self.assertIsNone(await task)
        current=json.loads(await self.client.get(self.key))
        self.assertNotIn("mcp_resources",current)
        self.assertEqual(current["resource"]["bearer"],raw["resource"]["bearer"])

    async def test_wrong_identity_is_not_cached(self):
        self.broker.bad_subject=True
        with self.assertRaises(ResourceCredentialUnavailable):await self.resolver.resolve(self.ticket,"terminal")
        self.assertNotIn("mcp_resources",json.loads(await self.client.get(self.key)))

    async def test_six_derived_bounded_tokens_share_one_usable_session_record(self):
        self.broker.size=8192
        current=json.loads(await self.client.get(self.key))
        current["resource"]["bearer"]="primary-fixture-".ljust(8192,"x")
        await self.client.set(self.key,json.dumps(current),keepttl=True)
        for hand in ["terminal","web","svc","infrastructure","reverse","serena"]:
            self.assertIsNotNone(await self.resolver.resolve(self.ticket,hand))
        raw=await self.client.get(self.key)
        self.assertGreater(len(raw),7*8192)
        self.assertLessEqual(len(raw),98304)
        self.assertIsNotNone(await self.store.get_session(self.ticket))
        for hand in ["terminal","web","svc","infrastructure","reverse","serena"]:
            self.assertIsNotNone(await self.resolver.resolve(self.ticket,hand))
        self.assertEqual(self.broker.calls,6)

    async def test_concurrent_different_resources_do_not_overwrite_each_other(self):
        self.broker.gate=asyncio.Event()
        a=asyncio.create_task(self.resolver.resolve(self.ticket,"terminal"))
        b=asyncio.create_task(self.resolver.resolve(self.ticket,"web"))
        async with asyncio.timeout(3):
            while self.broker.calls<2:await asyncio.sleep(.01)
        self.broker.gate.set()
        results=await asyncio.gather(a,b)
        self.assertEqual(sum(item is not None for item in results),1)
        # Retry observes the surviving record and merges the other audience.
        await self.resolver.resolve(self.ticket,"terminal")
        await self.resolver.resolve(self.ticket,"web")
        current=json.loads(await self.client.get(self.key))
        self.assertEqual(set(current["mcp_resources"]),{self.audience("terminal"),self.audience("web")})


class EscrowMergeUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_other_module_cas_winner_is_merged_without_reexchange(self):
        from unittest.mock import patch
        expiry=datetime.now(UTC)+timedelta(seconds=120)
        record={"issuer":"https://identity.example","subject":"user","client_id":"panel",
            "expires_at":expiry.isoformat(),"resource":{"bearer":"p"*100,"expires_at":expiry.isoformat()}}
        source=PrivateOidcResourceCredential(record["issuer"],"user","panel","aud:files",expiry,SecretStr("p"*100))
        class Client:
            raw=json.dumps(record)
            first=True
            async def get(self,key):return self.raw
            async def eval(self,script,count,key,old,new):
                if self.first:
                    self.first=False
                    current=json.loads(self.raw)
                    current["mcp_resources"]={"aud:terminal":{"bearer":"t"*100,"expires_at":expiry.isoformat()}}
                    self.raw=json.dumps(current)
                    return 0
                if self.raw!=old:return 0
                self.raw=new
                return 1
        client=Client()
        class Sessions:
            _client=client
            async def renew_session(self,*args):return 100
            async def get_session(self,*args):return SimpleNamespace(issuer=record["issuer"],subject="user",client_id="panel",expires_at=expiry)
            async def get_resource_credential(self,*args,**kwargs):return source
            def _key(self,*args):return "session"
        class Broker:
            calls=0
            async def exchange(self,*,source,identity,hand):
                self.calls+=1
                return PrivateOidcResourceCredential(identity.issuer,identity.subject,identity.client_id,"aud:"+hand,expiry,SecretStr("w"*100))
        broker=Broker()
        resolver=SessionResourceCredentials(sessions=Sessions(),provider=SimpleNamespace(issuer=record["issuer"],client_id="panel"),broker=broker)
        with patch("control_panel_api._resource_escrow.mcp_resource_audience",side_effect=lambda **kwargs:"aud:"+kwargs["hand"]):
            result=await resolver.resolve("ticket","web")
        self.assertIsNotNone(result)
        self.assertEqual(broker.calls,1)
        self.assertEqual(set(json.loads(client.raw)["mcp_resources"]),{"aud:web","aud:terminal"})
