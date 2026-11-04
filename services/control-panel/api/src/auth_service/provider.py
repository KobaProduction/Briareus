from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_identity.identity_provider import IdentityProviderError, ZitadelClient
from briareus_identity.identity_settings import McpAuthSettings
from briareus_json_values import JsonValue, StrictModel
from briareus_mcp_resources import allowed_resource_urls, resource_url
from briareus_oauth_sessions import OAuthSessionEvent
from briareus_oauth_sessions_client import record_oauth_session
from fastmcp.server.auth import AccessToken as FastMCPAccessToken
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.adapters.pydantic import PydanticAdapter
from mcp.server.auth.provider import AccessToken as SDKAccessToken
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from .identity import ZitadelTokenVerifier, oauth_storage
from .token_status import LocalTokenAuthority, TokenFamily

_RESOURCE_BINDING_TTL_SECONDS = 10 * 60
_TRANSACTION_TTL_SECONDS = 15 * 60
_FASTMCP_ACCESS_TOKEN_EXPIRY_SECONDS = 30 * 24 * 60 * 60
_FALLBACK_REFRESH_TOKEN_EXPIRY_SECONDS = 30 * 24 * 60 * 60
_REFRESH_REPLAY_SECONDS = 120.0
_REFRESH_REPLAY_WAIT_ATTEMPTS = 6
_REFRESH_REPLAY_WAIT_SECONDS = 0.05
_SESSION_TOUCH_INTERVAL_SECONDS = 60.0

logger = logging.getLogger(__name__)


class ResourceBinding(StrictModel):
    resource: str


class RefreshExchangeReplay(StrictModel):
    expires_at: float
    result: OAuthToken


@dataclass(frozen=True)
class RefreshFailureContext:
    client: OAuthClientInformationFull
    refresh_token: RefreshToken
    scopes: tuple[str, ...]
    resource: str
    session_id: str
    refresh_jti: str
    previous_upstream: tuple[str, str]
    current_upstream: tuple[str, str]


class MultiResourceZitadelProvider(OIDCProxy):
    """One OAuth issuer serving multiple exact MCP resource audiences."""

    def __init__(
        self,
        settings: McpAuthSettings,
        identity_provider: ZitadelClient,
        management: ControlPanelClient | None = None,
    ) -> None:
        self.settings = settings
        self._management = management
        self._identity_provider = identity_provider
        self._session_touch_times: dict[str, float] = {}
        self._resource_context: ContextVar[str | None] = ContextVar(
            "oauth_resource",
            default=None,
        )
        self._allowed_resources = allowed_resource_urls(settings.public_base_url)
        self._root_resource = resource_url(settings.public_base_url, "root")
        self._refresh_exchange_locks: dict[str, asyncio.Lock] = {}
        self._refresh_exchange_replays: dict[str, RefreshExchangeReplay] = {}

        super().__init__(
            config_url=identity_provider.settings.discovery_url,
            strict=True,
            client_id=identity_provider.settings.client_id,
            client_secret=identity_provider.settings.resolved_client_secret,
            base_url=settings.public_base_url,
            issuer_url=settings.public_base_url,
            token_verifier=ZitadelTokenVerifier(identity_provider),
            jwt_signing_key=settings.resolved_signing_key,
            client_storage=oauth_storage(settings),
            allowed_client_redirect_uris=list(settings.allowed_client_redirect_uris),
            require_authorization_consent="external",
            enable_cimd=False,
            forward_resource=False,
            token_endpoint_auth_method="client_secret_basic",
            extra_authorize_params={"scope": "openid profile email offline_access"},
            fallback_refresh_token_expiry_seconds=_FALLBACK_REFRESH_TOKEN_EXPIRY_SECONDS,
            fastmcp_access_token_expiry_seconds=_FASTMCP_ACCESS_TOKEN_EXPIRY_SECONDS,
        )

        self._resource_bindings: PydanticAdapter[ResourceBinding] = PydanticAdapter[
            ResourceBinding
        ](
            key_value=self._client_storage,
            pydantic_model=ResourceBinding,
            default_collection="koba-oauth-resource-bindings",
            raise_on_validation_error=True,
        )
        self._refresh_exchange_replay_store: PydanticAdapter[RefreshExchangeReplay] = (
            PydanticAdapter[RefreshExchangeReplay](
                key_value=self._client_storage,
                pydantic_model=RefreshExchangeReplay,
                default_collection="koba-oauth-refresh-replays",
                raise_on_validation_error=True,
            )
        )
        self._resource_issuers = {
            resource: JWTIssuer(
                issuer=str(self.issuer_url),
                audience=resource,
                signing_key=self._jwt_signing_key,
            )
            for resource in self._allowed_resources
        }
        self.token_authority = LocalTokenAuthority(
            storage=self._client_storage,
            mappings=self._jti_mapping_store,
            upstream_tokens=self._upstream_token_store,
            audience_for_token=self._jwt_audience_unverified,
            canonical_resource=self.canonical_resource,
            issuer_for_resource=self.issuer_for_resource,
            identity=identity_provider.settings,
            revocation_collection=settings.revocation_collection,
        )

    @staticmethod
    def _jwt_payload_unverified(token: str) -> dict[str, JsonValue]:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload).decode())
        except (IndexError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _claim_datetime(payload: dict[str, JsonValue], name: str) -> datetime | None:
        raw = payload.get(name)
        if not isinstance(raw, (int, float)):
            return None
        return datetime.fromtimestamp(float(raw), tz=UTC)

    @staticmethod
    def _client_name(client: OAuthClientInformationFull) -> str:
        value = getattr(client, "client_name", None)
        return str(value) if value else ""

    @staticmethod
    def _refresh_replay_key(client_id: str, refresh_token: str) -> str:
        return hashlib.sha256((client_id + "\0" + refresh_token).encode()).hexdigest()

    @staticmethod
    def _safe_id(value: str) -> str:
        return value[:12] if value else "-"

    @staticmethod
    def _safe_fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:12] if value else "-"

    def _log_refresh_flow(
        self,
        stage: str,
        *,
        flow_id: str,
        client_id: str,
        resource: str,
        refresh_jti: str = "",
        session_id: str = "",
        upstream_token_id: str = "",
        upstream_refresh_fingerprint: str = "",
        detail: str = "",
        level: int = logging.INFO,
    ) -> None:
        resource_path = urlsplit(resource).path or "/"
        logger.log(
            level,
            (
                "OAuth refresh flow stage=%s flow=%s client=%s resource=%s "
                "refresh_jti=%s session=%s upstream=%s upstream_fp=%s detail=%s"
            ),
            stage,
            flow_id,
            self._safe_fingerprint(client_id),
            resource_path,
            self._safe_id(refresh_jti),
            self._safe_id(session_id),
            self._safe_id(upstream_token_id),
            upstream_refresh_fingerprint[:12] or "-",
            detail or "-",
        )

    async def _load_refresh_exchange_replay(
        self,
        replay_key: str,
    ) -> RefreshExchangeReplay | None:
        now = time.time()
        cached = self._refresh_exchange_replays.get(replay_key)
        if cached is not None:
            if cached.expires_at > now:
                return cached
            self._refresh_exchange_replays.pop(replay_key, None)

        try:
            persisted = await self._refresh_exchange_replay_store.get(key=replay_key)
        except Exception as exc:
            logger.warning("Persistent refresh replay read failed: %s", exc)
            return None
        if persisted is None or persisted.expires_at <= now:
            return None
        self._refresh_exchange_replays[replay_key] = persisted
        return persisted

    async def _wait_refresh_exchange_replay(
        self,
        replay_key: str,
    ) -> RefreshExchangeReplay | None:
        for attempt in range(_REFRESH_REPLAY_WAIT_ATTEMPTS):
            replay = await self._load_refresh_exchange_replay(replay_key)
            if replay is not None:
                return replay
            if attempt + 1 < _REFRESH_REPLAY_WAIT_ATTEMPTS:
                await asyncio.sleep(_REFRESH_REPLAY_WAIT_SECONDS)
        return None

    async def _store_refresh_exchange_replay(
        self,
        replay_key: str,
        result: OAuthToken,
    ) -> None:
        replay = RefreshExchangeReplay(
            expires_at=time.time() + _REFRESH_REPLAY_SECONDS,
            result=result,
        )
        self._refresh_exchange_replays[replay_key] = replay
        try:
            await self._refresh_exchange_replay_store.put(
                key=replay_key,
                value=replay,
                ttl=_REFRESH_REPLAY_SECONDS,
            )
        except Exception as exc:
            logger.warning("Persistent refresh replay write failed: %s", exc)

    async def _upstream_refresh_identity(
        self,
        refresh_jti: str,
    ) -> tuple[str, str]:
        if not refresh_jti:
            return "", ""
        try:
            mapping = await self._jti_mapping_store.get(key=refresh_jti)
            if mapping is None:
                return "", ""
            upstream = await self._upstream_token_store.get(key=mapping.upstream_token_id)
        except Exception as exc:
            logger.warning("Upstream refresh state read failed: %s", exc)
            return "", ""
        if upstream is None or not upstream.refresh_token:
            return mapping.upstream_token_id, ""
        fingerprint = hashlib.sha256(upstream.refresh_token.encode()).hexdigest()
        return mapping.upstream_token_id, fingerprint

    async def _exchange_refresh_once(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
        resource: str,
    ) -> OAuthToken:
        context = self._resource_context.set(resource)
        try:
            return await super().exchange_refresh_token(client, refresh_token, scopes)
        finally:
            self._resource_context.reset(context)

    async def _session_id_from_jti(self, jti: str) -> str:
        if not jti:
            return ""
        mapping = await self._jti_mapping_store.get(key=jti)
        return mapping.upstream_token_id if mapping is not None else ""

    async def _session_id_from_token(self, token: str | None) -> str:
        if not token:
            return ""
        payload = self._jwt_payload_unverified(token)
        jti = payload.get("jti")
        return await self._session_id_from_jti(jti if isinstance(jti, str) else "")

    async def _record_session(self, event: OAuthSessionEvent) -> None:
        if self._management is None:
            return
        try:
            await asyncio.to_thread(record_oauth_session, self._management, event)
        except Exception as exc:
            logger.warning(
                "Management OAuth session event failed event=%s session=%s: %s",
                event.event,
                event.session_id[:16],
                exc,
            )

    async def _record_token_result(
        self,
        *,
        client: OAuthClientInformationFull,
        resource: str,
        result: OAuthToken,
        event_name: str,
        session_id: str = "",
    ) -> str:
        access_payload = self._jwt_payload_unverified(result.access_token)
        refresh_payload = self._jwt_payload_unverified(result.refresh_token or "")
        access_jti = access_payload.get("jti")
        refresh_jti = refresh_payload.get("jti")
        if not session_id:
            token_for_lookup = result.refresh_token or result.access_token
            session_id = await self._session_id_from_token(token_for_lookup)
        upstream = access_payload.get("upstream_claims")
        upstream_claims = upstream if isinstance(upstream, dict) else {}
        login = upstream_claims.get("preferred_username")
        subject = access_payload.get("sub") or upstream_claims.get("sub")
        await self._record_session(
            OAuthSessionEvent(
                session_id=session_id,
                client_id=client.client_id or "",
                client_name=self._client_name(client),
                resource=resource,
                login=str(login) if login else "",
                subject=str(subject) if subject else "",
                scopes=(result.scope or "").split(),
                status="active",
                event=event_name,
                access_jti=access_jti if isinstance(access_jti, str) else "",
                refresh_jti=refresh_jti if isinstance(refresh_jti, str) else "",
                access_expires_at=self._claim_datetime(access_payload, "exp"),
                refresh_expires_at=self._claim_datetime(refresh_payload, "exp"),
            )
        )
        return session_id

    @property
    def allowed_resources(self) -> frozenset[str]:
        return self._allowed_resources

    def issuer_for_resource(self, resource: str | None) -> JWTIssuer:
        return self._resource_issuers[self.canonical_resource(resource)]

    @property
    def jwt_issuer(self) -> JWTIssuer:
        return self.issuer_for_resource(self._resource_context.get() or self._root_resource)

    def canonical_resource(self, value: str | None) -> str:
        if not value:
            return self._root_resource
        parsed = urlsplit(value)
        candidate = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if candidate not in self._allowed_resources:
            raise ValueError(f"unsupported OAuth resource: {candidate}")
        return candidate

    @staticmethod
    def _transaction_id(url: str) -> str:
        query = parse_qs(urlsplit(url).query)
        for key in ("state", "txn_id"):
            values = query.get(key)
            if values and values[0]:
                return values[0]
        raise RuntimeError("OAuth transaction id missing from authorization redirect")

    @classmethod
    def _jwt_audience_unverified(cls, token: str) -> str | None:
        claims = cls._jwt_payload_unverified(token)
        audience = claims.get("aud")
        if isinstance(audience, str):
            return audience
        if isinstance(audience, list) and len(audience) == 1 and isinstance(audience[0], str):
            return audience[0]
        return None

    async def _extract_upstream_claims(
        self,
        idp_tokens: dict[str, JsonValue],
    ) -> dict[str, JsonValue] | None:
        access_token = idp_tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenError("invalid_grant", "ZITADEL access token is missing")
        validated = await self._token_validator.verify_token(access_token)
        if validated is None or not validated.subject:
            raise TokenError("invalid_grant", "ZITADEL identity is unavailable or unauthorized")
        return {
            "iss": self._identity_provider.settings.canonical_issuer,
            "sub": validated.subject,
            "preferred_username": str(validated.claims.get("preferred_username", "")),
            "identity_provider": "zitadel",
        }

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        resource = self.canonical_resource(params.resource)
        redirect = await super().authorize(
            client,
            params.model_copy(update={"resource": None}),
        )
        txn_id = self._transaction_id(redirect)
        transaction = await self._transaction_store.get(key=txn_id)
        if transaction is None:
            raise RuntimeError("OAuth transaction disappeared before resource binding")
        await self._transaction_store.put(
            key=txn_id,
            value=transaction.model_copy(update={"resource": resource}),
            ttl=_TRANSACTION_TTL_SECONDS,
        )
        return redirect

    async def _handle_idp_callback(
        self,
        request: Request,
    ) -> HTMLResponse | RedirectResponse:
        txn_id = request.query_params.get("state")
        transaction = await self._transaction_store.get(key=txn_id) if txn_id else None
        resource = (
            self.canonical_resource(transaction.resource) if transaction is not None else None
        )

        response = await super()._handle_idp_callback(request)

        if resource and isinstance(response, RedirectResponse):
            location = response.headers.get("location", "")
            codes = parse_qs(urlsplit(location).query).get("code")
            if codes and codes[0]:
                await self._resource_bindings.put(
                    key=codes[0],
                    value=ResourceBinding(resource=resource),
                    ttl=_RESOURCE_BINDING_TTL_SECONDS,
                )
        return response

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        loaded = await super().load_authorization_code(client, authorization_code)
        if loaded is None:
            return None
        binding = await self._resource_bindings.get(key=authorization_code)
        if binding is None:
            return None
        resource = self.canonical_resource(binding.resource)
        return loaded.model_copy(update={"resource": resource})

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        resource = self.canonical_resource(authorization_code.resource)
        token = self._resource_context.set(resource)
        try:
            result = await super().exchange_authorization_code(client, authorization_code)
            await self._record_token_result(
                client=client,
                resource=resource,
                result=result,
                event_name="authorized",
            )
            return result
        finally:
            self._resource_context.reset(token)
            await self._resource_bindings.delete(key=authorization_code.code)

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        if await self._refresh_family(refresh_token, client.client_id or "") is None:
            return None
        payload = self._jwt_payload_unverified(refresh_token)
        refresh_jti = payload.get("jti")
        session_id = await self._session_id_from_jti(
            refresh_jti if isinstance(refresh_jti, str) else ""
        )
        audience = self._jwt_audience_unverified(refresh_token)
        try:
            resource = self.canonical_resource(audience)
        except ValueError:
            return None

        loaded = await super().load_refresh_token(client, refresh_token)
        if loaded is not None:
            return loaded.model_copy(update={"resource": resource})

        client_id = client.client_id or ""
        replay_key = self._refresh_replay_key(client_id, refresh_token)
        replay = await self._wait_refresh_exchange_replay(replay_key)
        if replay is not None:
            self._log_refresh_flow(
                "load_replay",
                flow_id=replay_key[:12],
                client_id=client_id,
                resource=resource,
                refresh_jti=refresh_jti if isinstance(refresh_jti, str) else "",
                session_id=session_id,
                detail="rotated client refresh token replayed from persistent storage",
            )
            scope_text = replay.result.scope
            if not scope_text:
                raw_scope = payload.get("scope")
                scope_text = raw_scope if isinstance(raw_scope, str) else ""
            return RefreshToken(
                token=refresh_token,
                client_id=client_id,
                scopes=scope_text.split(),
                expires_at=int(replay.expires_at),
                resource=resource,
            )

        self._log_refresh_flow(
            "load_missing",
            flow_id=replay_key[:12],
            client_id=client_id,
            resource=resource,
            refresh_jti=refresh_jti if isinstance(refresh_jti, str) else "",
            session_id=session_id,
            detail="client refresh metadata missing and no replay result exists",
            level=logging.WARNING,
        )
        await self._record_session(
            OAuthSessionEvent(
                session_id=session_id,
                client_id=client_id or str(payload.get("client_id") or ""),
                client_name=self._client_name(client),
                resource=resource,
                status="invalid",
                event="refresh_missing",
                refresh_jti=refresh_jti if isinstance(refresh_jti, str) else "",
                error_type="invalid_grant",
                error_message=("Refresh token metadata is missing, rotated, expired, or revoked"),
            )
        )
        return None

    def _prune_refresh_replays(self) -> None:
        now = time.time()
        expired = [
            key
            for key, replay in self._refresh_exchange_replays.items()
            if replay.expires_at <= now
        ]
        for key in expired:
            self._refresh_exchange_replays.pop(key, None)
            lock = self._refresh_exchange_locks.get(key)
            if lock is not None and not lock.locked():
                self._refresh_exchange_locks.pop(key, None)

    async def _record_refresh_failure(
        self,
        context: RefreshFailureContext,
        error: Exception,
    ) -> None:
        client = context.client
        refresh_token = context.refresh_token
        scopes = context.scopes
        resource = context.resource
        session_id = context.session_id
        old_refresh_jti = context.refresh_jti
        before_token_id, before_refresh_fingerprint = context.previous_upstream
        after_token_id, after_refresh_fingerprint = context.current_upstream
        client_id = client.client_id or ""
        flow_id = self._refresh_replay_key(client_id, refresh_token.token)[:12]
        reauth_required = "bad_refresh_token" in str(error).casefold()
        self._log_refresh_flow(
            "terminal_failure",
            flow_id=flow_id,
            client_id=client_id,
            resource=resource,
            refresh_jti=old_refresh_jti,
            session_id=session_id,
            upstream_token_id=after_token_id or before_token_id,
            upstream_refresh_fingerprint=(after_refresh_fingerprint or before_refresh_fingerprint),
            detail=(
                "reauth_required=true"
                if reauth_required
                else f"reauth_required=false error={type(error).__name__}"
            ),
            level=logging.ERROR,
        )
        await self._record_session(
            OAuthSessionEvent(
                session_id=session_id,
                client_id=client_id,
                client_name=self._client_name(client),
                resource=resource,
                scopes=list(scopes),
                status="invalid" if reauth_required else "refresh_error",
                event=("refresh_reauth_required" if reauth_required else "refresh_error"),
                refresh_jti=old_refresh_jti,
                error_type=type(error).__name__,
                error_message=str(error)[:2048],
            )
        )
        if reauth_required:
            await self._refresh_token_store.delete(
                key=hashlib.sha256(refresh_token.token.encode()).hexdigest()
            )
            if old_refresh_jti:
                await self._jti_mapping_store.delete(key=old_refresh_jti)
            self._log_refresh_flow(
                "invalidated_dead_refresh",
                flow_id=flow_id,
                client_id=client_id,
                resource=resource,
                refresh_jti=old_refresh_jti,
                session_id=session_id,
                detail="deleted client refresh metadata and JTI mapping",
                level=logging.WARNING,
            )

    async def _refresh_family(self, token: str, client_id: str) -> TokenFamily | None:
        original = self.token_authority.verified_claims(token, "refresh")
        if original is None or original.client_id != client_id:
            return None
        family = await self.token_authority.resolve(token, "refresh")
        if family is not None:
            return family if await self.token_authority.is_active(family) else None
        replay = await self._wait_refresh_exchange_replay(
            self._refresh_replay_key(client_id, token)
        )
        if replay is None:
            return None
        current = await self.token_authority.access_family(replay.result.access_token)
        if (
            current is None
            or current.claims.client_id != client_id
            or current.claims.aud != original.aud
        ):
            return None
        if not set(current.claims.scope.split()).issubset(original.scope.split()):
            return None
        if (
            original.upstream_claims is not None
            and original.upstream_claims != current.claims.upstream_claims
        ):
            return None
        return current

    async def _guard_refresh_result(
        self, result: OAuthToken, client_id: str, resource: str
    ) -> OAuthToken:
        family = await self.token_authority.access_family(result.access_token)
        if family is None or family.claims.client_id != client_id or family.claims.aud != resource:
            raise TokenError("invalid_grant", "OAuth refresh family is inactive")
        return result

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if await self._refresh_family(refresh_token.token, client.client_id or "") is None:
            raise TokenError("invalid_grant", "OAuth refresh family is inactive")
        resource = self.canonical_resource(refresh_token.resource)
        client_id = client.client_id or ""
        replay_key = self._refresh_replay_key(client_id, refresh_token.token)

        self._prune_refresh_replays()

        refresh_payload = self._jwt_payload_unverified(refresh_token.token)
        refresh_jti = refresh_payload.get("jti")
        old_refresh_jti = refresh_jti if isinstance(refresh_jti, str) else ""
        session_id = await self._session_id_from_jti(old_refresh_jti)
        flow_id = replay_key[:12]
        self._log_refresh_flow(
            "request",
            flow_id=flow_id,
            client_id=client_id,
            resource=resource,
            refresh_jti=old_refresh_jti,
            session_id=session_id,
            detail=f"scope_count={len(scopes)}",
        )

        lock = self._refresh_exchange_locks.setdefault(replay_key, asyncio.Lock())
        async with lock:
            replay = await self._load_refresh_exchange_replay(replay_key)
            if replay is not None:
                self._log_refresh_flow(
                    "replay_hit",
                    flow_id=flow_id,
                    client_id=client_id,
                    resource=resource,
                    refresh_jti=old_refresh_jti,
                    session_id=session_id,
                    detail="returning previously rotated token pair",
                )
                await self._record_token_result(
                    client=client,
                    resource=resource,
                    result=replay.result,
                    event_name="refresh_replay",
                    session_id=session_id,
                )
                return await self._guard_refresh_result(replay.result, client_id, resource)

            before_token_id, before_refresh_fingerprint = await self._upstream_refresh_identity(
                old_refresh_jti
            )
            self._log_refresh_flow(
                "upstream_exchange",
                flow_id=flow_id,
                client_id=client_id,
                resource=resource,
                refresh_jti=old_refresh_jti,
                session_id=session_id,
                upstream_token_id=before_token_id,
                upstream_refresh_fingerprint=before_refresh_fingerprint,
                detail="calling ZITADEL refresh endpoint",
            )
            try:
                result = await self._exchange_refresh_once(client, refresh_token, scopes, resource)
            except Exception as exc:
                error = exc
                self._log_refresh_flow(
                    "upstream_failed",
                    flow_id=flow_id,
                    client_id=client_id,
                    resource=resource,
                    refresh_jti=old_refresh_jti,
                    session_id=session_id,
                    upstream_token_id=before_token_id,
                    upstream_refresh_fingerprint=before_refresh_fingerprint,
                    detail=f"{type(exc).__name__}:{str(exc)[:240]}",
                    level=logging.WARNING,
                )
                replay = await self._wait_refresh_exchange_replay(replay_key)
                if replay is not None:
                    self._log_refresh_flow(
                        "replay_recovered",
                        flow_id=flow_id,
                        client_id=client_id,
                        resource=resource,
                        refresh_jti=old_refresh_jti,
                        session_id=session_id,
                        detail="parallel refresh completed while upstream request failed",
                    )
                    await self._record_token_result(
                        client=client,
                        resource=resource,
                        result=replay.result,
                        event_name="refresh_replay_recovered",
                        session_id=session_id,
                    )
                    return await self._guard_refresh_result(replay.result, client_id, resource)

                after_token_id, after_refresh_fingerprint = await self._upstream_refresh_identity(
                    old_refresh_jti
                )
                upstream_rotated_elsewhere = (
                    isinstance(error, TokenError)
                    and bool(before_token_id)
                    and before_token_id == after_token_id
                    and bool(before_refresh_fingerprint)
                    and bool(after_refresh_fingerprint)
                    and before_refresh_fingerprint != after_refresh_fingerprint
                )
                self._log_refresh_flow(
                    "post_failure_state",
                    flow_id=flow_id,
                    client_id=client_id,
                    resource=resource,
                    refresh_jti=old_refresh_jti,
                    session_id=session_id,
                    upstream_token_id=after_token_id,
                    upstream_refresh_fingerprint=after_refresh_fingerprint,
                    detail=f"rotated_elsewhere={str(upstream_rotated_elsewhere).lower()}",
                )
                if upstream_rotated_elsewhere:
                    self._log_refresh_flow(
                        "retry_after_rotation",
                        flow_id=flow_id,
                        client_id=client_id,
                        resource=resource,
                        refresh_jti=old_refresh_jti,
                        session_id=session_id,
                        upstream_token_id=after_token_id,
                        upstream_refresh_fingerprint=after_refresh_fingerprint,
                        detail="retrying once with refreshed upstream state",
                    )
                    try:
                        result = await self._exchange_refresh_once(
                            client, refresh_token, scopes, resource
                        )
                    except Exception as retry_exc:
                        error = retry_exc
                    else:
                        self._log_refresh_flow(
                            "success_after_rotation",
                            flow_id=flow_id,
                            client_id=client_id,
                            resource=resource,
                            refresh_jti=old_refresh_jti,
                            session_id=session_id,
                            upstream_token_id=after_token_id,
                            upstream_refresh_fingerprint=after_refresh_fingerprint,
                        )
                        await self._store_refresh_exchange_replay(replay_key, result)
                        await self._record_token_result(
                            client=client,
                            resource=resource,
                            result=result,
                            event_name="refresh_success_after_upstream_race",
                            session_id=session_id,
                        )
                        return await self._guard_refresh_result(result, client_id, resource)

                await self._record_refresh_failure(
                    RefreshFailureContext(
                        client,
                        refresh_token,
                        tuple(scopes),
                        resource,
                        session_id,
                        old_refresh_jti,
                        (before_token_id, before_refresh_fingerprint),
                        (after_token_id, after_refresh_fingerprint),
                    ),
                    error,
                )
                if error is exc:
                    raise
                raise error from exc

            self._log_refresh_flow(
                "success",
                flow_id=flow_id,
                client_id=client_id,
                resource=resource,
                refresh_jti=old_refresh_jti,
                session_id=session_id,
                upstream_token_id=before_token_id,
                upstream_refresh_fingerprint=before_refresh_fingerprint,
            )
            await self._store_refresh_exchange_replay(replay_key, result)
            await self._record_token_result(
                client=client,
                resource=resource,
                result=result,
                event_name="refresh_success",
                session_id=session_id,
            )
            return await self._guard_refresh_result(result, client_id, resource)

    async def _revoke_upstream_family(
        self,
        family: TokenFamily,
        token: SDKAccessToken | RefreshToken,
    ) -> None:
        if isinstance(token, RefreshToken):
            await self._refresh_token_store.delete(
                key=hashlib.sha256(token.token.encode()).hexdigest()
            )
        upstream = await self._upstream_token_store.get(key=family.upstream_token_id)
        if upstream is None:
            return
        try:
            await asyncio.to_thread(
                self._identity_provider.revoke,
                upstream.refresh_token or upstream.access_token,
            )
        except IdentityProviderError:
            logger.warning("Local OAuth family revoked; upstream ZITADEL revocation unavailable")

    async def revoke_token(
        self,
        token: SDKAccessToken | RefreshToken,
    ) -> None:
        payload = self._jwt_payload_unverified(token.token)
        jti = payload.get("jti")
        token_jti = jti if isinstance(jti, str) else ""
        session_id = await self._session_id_from_jti(token_jti)
        audience = self._jwt_audience_unverified(token.token)
        try:
            resource = self.canonical_resource(audience)
        except ValueError:
            return

        if isinstance(token, RefreshToken):
            family = await self._refresh_family(token.token, token.client_id)
            if family is not None:
                family = await self.token_authority.revoke_family(family, token.client_id)
        else:
            family = await self.token_authority.revoke(token.token, "access", token.client_id)
        if family is None:
            return
        await self._revoke_upstream_family(family, token)

        await self._record_session(
            OAuthSessionEvent(
                session_id=session_id,
                client_id=token.client_id,
                resource=resource,
                scopes=list(token.scopes),
                status="revoked",
                event="revoked",
                access_jti=token_jti if isinstance(token, SDKAccessToken) else "",
                refresh_jti=token_jti if isinstance(token, RefreshToken) else "",
            )
        )

    async def load_access_token(self, token: str) -> FastMCPAccessToken | None:
        if not (await self.token_authority.status(token)).active:
            return None
        payload = self._jwt_payload_unverified(token)
        access_jti = payload.get("jti")
        token_jti = access_jti if isinstance(access_jti, str) else ""
        session_id = await self._session_id_from_jti(token_jti)
        audience = self._jwt_audience_unverified(token)
        try:
            resource = self.canonical_resource(audience)
        except ValueError:
            return None

        context = self._resource_context.set(resource)
        try:
            access = await super().load_access_token(token)
        finally:
            self._resource_context.reset(context)

        upstream = payload.get("upstream_claims")
        upstream_claims = upstream if isinstance(upstream, dict) else {}
        login = upstream_claims.get("preferred_username")
        client_id = str(payload.get("client_id") or "")
        if access is None:
            await self._record_session(
                OAuthSessionEvent(
                    session_id=session_id,
                    client_id=client_id,
                    resource=resource,
                    login=str(login) if login else "",
                    status="invalid",
                    event="access_invalid",
                    access_jti=token_jti,
                    error_type="invalid_token",
                    error_message="Access token validation or upstream session failed",
                )
            )
            return None

        now = time.monotonic()
        last_touch = self._session_touch_times.get(session_id, 0.0)
        if session_id and now - last_touch >= _SESSION_TOUCH_INTERVAL_SECONDS:
            self._session_touch_times[session_id] = now
            await self._record_session(
                OAuthSessionEvent(
                    session_id=session_id,
                    client_id=access.client_id,
                    resource=resource,
                    login=str(login) if login else "",
                    subject=access.subject or "",
                    scopes=list(access.scopes),
                    status="active",
                    event="access_used",
                    access_jti=token_jti,
                    access_expires_at=self._claim_datetime(payload, "exp"),
                )
            )

        return FastMCPAccessToken(
            token=token,
            client_id=access.client_id,
            scopes=list(access.scopes),
            expires_at=access.expires_at,
            resource=resource,
            subject=access.subject,
            claims=dict(access.claims or {}),
        )
