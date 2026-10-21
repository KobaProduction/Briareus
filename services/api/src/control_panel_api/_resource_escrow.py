"""Per-MCP tokens share the browser session's revocable Valkey record."""
import json
from datetime import UTC, datetime

from pydantic import SecretStr
from valkey.exceptions import ValkeyError

from ._oidc import _unique_oidc_fields
from ._oidc_id_token import OidcIdentityRejected, VerifiedOidcIdentity
from ._oidc_origin_policy import MCP_HANDS, mcp_resource_audience
from ._oidc_resource import PrivateOidcResourceCredential
from ._resource_broker import ResourceCredentialUnavailable

MAX_SESSION_BYTES = 98304
_CACHE = "mcp_resources"
_COMMIT = ("if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end "
           "local ttl=redis.call('PTTL',KEYS[1]); if ttl<=0 then return 0 end "
           "redis.call('SET',KEYS[1],ARGV[2],'PX',ttl); return 1")


class SessionResourceCredentials:
    def __init__(self, *, sessions, provider, broker=None):
        self.sessions, self.provider, self.broker = sessions, provider, broker

    def _read(self, raw, identity, audience):
        if not isinstance(raw,str) or len(raw)>MAX_SESSION_BYTES:
            return None
        try:
            value=json.loads(raw,object_pairs_hook=_unique_oidc_fields)
            source=value["resource"]
            cache=value.get(_CACHE,{})
            allowed={mcp_resource_audience(issuer=identity.issuer,client_id=identity.client_id,hand=hand)
                     for hand in MCP_HANDS-{"files"}}
            if not isinstance(cache,dict) or len(cache)>len(allowed) or not set(cache)<=allowed:
                return None
            resource=cache.get(audience)
            if not isinstance(resource,dict) or set(resource)!={"bearer","expires_at"}:
                return None
            expiry=min(datetime.fromisoformat(value["expires_at"]),datetime.fromisoformat(source["expires_at"]),
                datetime.fromisoformat(resource["expires_at"]),identity.expires_at)
            bearer=resource["bearer"]
            if (value["issuer"]!=identity.issuer or value["subject"]!=identity.subject
                or value["client_id"]!=identity.client_id or expiry.tzinfo is None or expiry<=datetime.now(UTC)
                or not isinstance(bearer,str) or not 80<=len(bearer)<=8192 or not bearer.isascii()
                or any(char.isspace() for char in bearer)):
                return None
            return PrivateOidcResourceCredential(identity.issuer,identity.subject,identity.client_id,
                audience,expiry,SecretStr(bearer))
        except (ValueError,TypeError,KeyError,AttributeError):
            return None

    async def resolve(self, ticket: str, hand: str):
        audience=mcp_resource_audience(issuer=self.provider.issuer,client_id=self.provider.client_id,hand=hand)
        # Refresh rotation remains exclusively with the original OIDC client.
        # Derived access tokens never have a refresh token of their own.
        await self.sessions.renew_session(ticket,self.provider)
        session=await self.sessions.get_session(ticket)
        if session is None:
            return None
        identity=VerifiedOidcIdentity(session.issuer,session.subject,session.client_id,session.expires_at)
        primary=mcp_resource_audience(issuer=identity.issuer,client_id=identity.client_id,hand="files")
        source=await self.sessions.get_resource_credential(ticket,issuer=identity.issuer,
            client_id=identity.client_id,audience=primary)
        if source is None:
            return None
        if hand=="files":
            return source
        if self.broker is None:
            raise ResourceCredentialUnavailable("Resource broker is not configured")
        key=self.sessions._key("session",ticket)
        try:
            raw=await self.sessions._client.get(key)
            cached=self._read(raw,identity,audience)
            if cached:
                return cached
            if not isinstance(raw,str) or len(raw)>MAX_SESSION_BYTES:
                return None
            value=json.loads(raw,object_pairs_hook=_unique_oidc_fields)
            if (value["issuer"]!=identity.issuer or value["subject"]!=identity.subject
                or value["client_id"]!=identity.client_id
                or value["resource"]["bearer"]!=source.bearer.get_secret_value()):
                return None
            resource=await self.broker.exchange(source=source,identity=identity,hand=hand)
            if (not isinstance(resource,PrivateOidcResourceCredential) or resource.issuer!=identity.issuer
                or resource.subject!=identity.subject or resource.client_id!=identity.client_id
                or resource.audience!=audience or resource.expires_at>min(source.expires_at,identity.expires_at)
                or resource.expires_at<=datetime.now(UTC)):
                raise ResourceCredentialUnavailable("Resource broker identity binding invalid")
            cache=dict(value.get(_CACHE,{}))
            allowed={mcp_resource_audience(issuer=identity.issuer,client_id=identity.client_id,hand=item)
                     for item in MCP_HANDS-{"files"}}
            if not set(cache)<=allowed or len(cache)>len(allowed):
                return None
            cache[audience]={"bearer":resource.bearer.get_secret_value(),"expires_at":resource.expires_at.isoformat()}
            updated=json.dumps({**value,_CACHE:cache},separators=(',',':'))
            if len(updated)>MAX_SESSION_BYTES:
                return None
            for _ in range(4):
                if await self.sessions._client.eval(_COMMIT,1,key,raw,updated)==1:
                    return self._read(await self.sessions._client.get(key),identity,audience)
                raw=await self.sessions._client.get(key)
                cached=self._read(raw,identity,audience)
                if cached:return cached
                if not isinstance(raw,str) or len(raw)>MAX_SESSION_BYTES:return None
                value=json.loads(raw,object_pairs_hook=_unique_oidc_fields)
                # Merge only credentials derived from the unchanged source.
                # Refresh/logout racing this write must never be overwritten.
                if (value.get("issuer")!=identity.issuer or value.get("subject")!=identity.subject
                    or value.get("client_id")!=identity.client_id
                    or value.get("resource",{}).get("bearer")!=source.bearer.get_secret_value()):return None
                cache=dict(value.get(_CACHE,{}))
                if not set(cache)<=allowed:return None
                cache[audience]={"bearer":resource.bearer.get_secret_value(),"expires_at":resource.expires_at.isoformat()}
                updated=json.dumps({**value,_CACHE:cache},separators=(',',':'))
                if len(updated)>MAX_SESSION_BYTES:return None
            raise ResourceCredentialUnavailable("Private resource escrow changed concurrently")
        except OidcIdentityRejected:
            await self.sessions.delete_session(ticket)
            raise
        except (ValkeyError,ValueError,TypeError,KeyError):
            raise ResourceCredentialUnavailable("Private resource escrow unavailable") from None
