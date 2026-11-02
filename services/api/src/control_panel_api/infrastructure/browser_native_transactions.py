"""Native init, PoW and OTP transitions retain their atomic Valkey scripts."""

from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from valkey.exceptions import ValkeyError

from control_panel_api._native_state_scripts import (
    CANCEL_LOGIN,
    CLAIM_INIT,
    CLAIM_OTP_FINISH,
    CLAIM_OTP_START,
    COMPLETE_LOGIN,
    CONFIRM_OTP_START,
    CONFIRM_POW,
    STAGE_OTP,
)
from control_panel_api._oidc_origin_policy import validate_files_resource_intent
from control_panel_api.domain.native_login import PrivateNativeOtpPending, PrivateNativePending
from control_panel_api.domain.oidc_identity import (
    OidcSessionStoreUnavailable,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
    VerifiedRefreshCredential,
)
from control_panel_api.infrastructure.browser_records import (
    StoredNativeClaim,
    StoredNativeInit,
    StoredNativeOtp,
    browser_record,
    private_secret,
)
from control_panel_api.infrastructure.browser_session_preparation import prepare_browser_session
from control_panel_api.infrastructure.browser_storage import BROWSER_TOKEN, BrowserStorageContext
from control_panel_api.infrastructure.browser_write_records import (
    NativeInitWrite,
    NativeOtpMethodWrite,
    NativeOtpWrite,
    encode_browser_write,
)
from control_panel_api.infrastructure.valkey_scripts import eval_script

_MAX_TRANSACTION_SECONDS = 300


class ValkeyNativeTransactions:
    def __init__(self, storage: BrowserStorageContext) -> None:
        self._storage = storage

    async def save_native_init(
        self,
        *,
        state: str,
        nonce: str,
        verifier: str,
        issuer: str,
        client_id: str,
        csrf: SecretStr,
        provider_cookie: SecretStr,
        seconds: int,
        resource_audience: str | None = None,
    ) -> None:
        """Escrow once per state; never forward provider session to browser."""
        if (
            BROWSER_TOKEN.fullmatch(state) is None
            or BROWSER_TOKEN.fullmatch(nonce) is None
            or BROWSER_TOKEN.fullmatch(verifier) is None
            or type(seconds) is not int
            or not 1 <= seconds <= _MAX_TRANSACTION_SECONDS
            or not private_secret(csrf)
            or not private_secret(provider_cookie)
            or not issuer.startswith("https://")
            or not client_id
        ):
            raise OidcSessionStoreUnavailable("untrusted native Init escrow")
        validate_files_resource_intent(
            issuer=issuer, client_id=client_id, resource_audience=resource_audience
        )
        deadline = datetime.now(UTC) + timedelta(seconds=seconds)
        payload = encode_browser_write(
            NativeInitWrite(
                stage="init",
                deadline_ms=int(deadline.timestamp() * 1000),
                state=state,
                expires_at=deadline.isoformat(),
                resource_audience=resource_audience,
                nonce=nonce,
                verifier=verifier,
                issuer=issuer,
                client_id=client_id,
                csrf=csrf.get_secret_value(),
                provider_cookie=provider_cookie.get_secret_value(),
            )
        )
        try:
            created = await self._storage.client.set(
                self._storage.key("native-init", state),
                payload,
                ex=seconds,
                nx=True,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native Rauthy Init store unavailable") from None
        if not created:
            raise OidcSessionStoreUnavailable("native Rauthy Init collision")

    async def native_init_is_current(self, *, state: str, issuer: str, client_id: str) -> bool:
        try:
            raw = await self._storage.client.get(self._storage.key("native-init", state))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native Init state unavailable") from None
        if raw is None or not isinstance(raw, str) or len(raw) > 16_384:
            return False
        try:
            payload = browser_record(raw, StoredNativeInit)
            return (
                payload.expires_at.tzinfo is not None
                and payload.expires_at > datetime.now(UTC)
                and payload.state == state
                and payload.issuer == issuer
                and payload.client_id == client_id
                and payload.provider_cookie.startswith("__Host-RauthySession=")
            )
        except (ValueError, TypeError, KeyError):
            return False

    async def reserve_native_pow(self, *, state: str, issuer: str, client_id: str) -> bool:
        """Claim at most one public PoW challenge per pending Init attempt.

        This is NOT provider authentication: atomic NX caps the number of
        challenge issuances even when two callers race on the same cookie.
        The pending Init must be rechecked after NX in case logout removed
        it concurrently. Failure burns the reservation (fail-closed).
        """
        if not await self.native_init_is_current(state=state, issuer=issuer, client_id=client_id):
            return False
        try:
            reserved = await self._storage.client.set(
                self._storage.key("native-pow", state),
                "reserved",
                nx=True,
                ex=_MAX_TRANSACTION_SECONDS,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native PoW reservation unavailable") from None
        if not reserved:
            return False
        return await self.native_init_is_current(state=state, issuer=issuer, client_id=client_id)

    async def confirm_native_pow(self, *, state: str, issuer: str, client_id: str) -> bool:
        """Mark successful upstream issuance, not an earlier in-flight reservation."""
        try:
            result = await eval_script(
                self._storage.client,
                CONFIRM_POW,
                2,
                self._storage.key("native-init", state),
                self._storage.key("native-pow", state),
                issuer,
                client_id,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native PoW confirmation unavailable") from None
        return type(result) is int and result == 1

    async def consume_native_init(
        self, *, state: str, issuer: str, client_id: str
    ) -> PrivateNativePending | None:
        """Atomically claim once while retaining a cancelable, secret-free marker."""
        claim = secrets.token_urlsafe(32)
        try:
            raw = await eval_script(
                self._storage.client,
                CLAIM_INIT,
                2,
                self._storage.key("native-init", state),
                self._storage.key("native-pow", state),
                issuer,
                client_id,
                claim,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native Init claim unavailable") from None
        if not isinstance(raw, str) or len(raw) > 16_384:
            return None
        try:
            value = browser_record(raw, StoredNativeInit)
            validate_files_resource_intent(
                issuer=issuer, client_id=client_id, resource_audience=value.resource_audience
            )
            if (
                value.expires_at.tzinfo is None
                or value.expires_at <= datetime.now(UTC)
                or (value.state, value.issuer, value.client_id) != (state, issuer, client_id)
                or not re.fullmatch(r"__Host-RauthySession=[!-~]{32,4096}", value.provider_cookie)
                or ";" in value.provider_cookie
            ):
                return None
            return PrivateNativePending(
                state=state,
                issuer=issuer,
                client_id=client_id,
                nonce=value.nonce,
                verifier=SecretStr(value.verifier),
                csrf=SecretStr(value.csrf),
                provider_cookie=SecretStr(value.provider_cookie),
                expires_at=value.expires_at,
                claim_id=SecretStr(claim),
                resource_audience=value.resource_audience,
            )
        except (ValueError, TypeError, KeyError):
            return None

    async def native_claim_is_current(self, pending: PrivateNativePending) -> bool:
        try:
            raw = await self._storage.client.get(self._storage.key("native-init", pending.state))
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native claim state unavailable") from None
        if not isinstance(raw, str) or len(raw) > 4096:
            return False
        try:
            value = browser_record(raw, StoredNativeClaim)
            return (
                value.claim == pending.claim_id.get_secret_value()
                and pending.expires_at > datetime.now(UTC)
            )
        except (ValueError, AttributeError, TypeError):
            return False

    async def complete_native_login(
        self,
        *,
        pending: PrivateNativePending,
        identity: VerifiedOidcIdentity,
        resource: PrivateOidcResourceCredential | None = None,
        refresh: VerifiedRefreshCredential | None = None,
    ) -> tuple[str, int] | None:
        if (
            identity.issuer.rstrip("/") != pending.issuer.rstrip("/")
            or identity.client_id != pending.client_id
            or (resource.audience if resource else None) != pending.resource_audience
            or pending.expires_at <= datetime.now(UTC)
        ):
            return None
        prepared = prepare_browser_session(identity, resource=resource, refresh=refresh)
        try:
            result = await eval_script(
                self._storage.client,
                COMPLETE_LOGIN,
                2,
                self._storage.key("native-init", pending.state),
                self._storage.key("session", prepared.ticket),
                pending.claim_id.get_secret_value(),
                json.dumps(
                    prepared.record.model_dump(mode="json", exclude_unset=True, exclude_none=True),
                    separators=(",", ":"),
                ),
                int(prepared.deadline.timestamp() * 1000),
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native session completion unavailable") from None
        if result == -1:
            raise OidcSessionStoreUnavailable("native session collision")
        if type(result) is not int or result != 1:
            return None
        return prepared.ticket, prepared.seconds

    async def stage_native_otp(
        self,
        *,
        pending: PrivateNativePending,
        login_code: SecretStr,
        methods: tuple[tuple[str, SecretStr], ...],
        provider_cookie: SecretStr,
        csrf_token: SecretStr,
    ) -> bool:
        """Atomically escrow the original signed-code context after first factor.

        OTP methods/IdP code/PKCE/provider cookies remain PRIVATE in Valkey.
        Browser only receives method indexes and human-readable kinds.
        Cancellation can delete this state before/after the CAS.
        """
        if (
            not private_secret(login_code)
            or re.fullmatch(r"[A-Za-z0-9_-]{16,256}", login_code.get_secret_value(), re.ASCII)
            is None
            or not 1 <= len(methods) <= 10
            or any(
                kind != "email"
                or not private_secret(otp_id)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", otp_id.get_secret_value(), re.ASCII)
                is None
                for kind, otp_id in methods
            )
            or not private_secret(provider_cookie)
            or not private_secret(csrf_token)
            or re.fullmatch(r"[A-Za-z0-9]{32}", csrf_token.get_secret_value(), re.ASCII) is None
            or pending.expires_at <= datetime.now(UTC)
        ):
            return False
        record = NativeOtpWrite(
            stage="otp_ready",
            claim=pending.claim_id.get_secret_value(),
            deadline_ms=int(pending.expires_at.timestamp() * 1000),
            state=pending.state,
            issuer=pending.issuer,
            client_id=pending.client_id,
            nonce=pending.nonce,
            verifier=pending.verifier.get_secret_value(),
            csrf=csrf_token.get_secret_value(),
            provider_cookie=provider_cookie.get_secret_value(),
            resource_audience=pending.resource_audience,
            otp_login_code=login_code.get_secret_value(),
            methods=tuple(
                NativeOtpMethodWrite(kind=kind, id=otp_id.get_secret_value())
                for kind, otp_id in methods
            ),
        )
        try:
            result = await eval_script(
                self._storage.client,
                STAGE_OTP,
                1,
                self._storage.key("native-init", pending.state),
                pending.claim_id.get_secret_value(),
                encode_browser_write(record),
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native OTP escrow unavailable") from None
        return type(result) is int and result == 1

    @staticmethod
    def _private_otp_pending(
        raw: object, *, state: str, issuer: str, client_id: str, attempt_id: SecretStr
    ) -> PrivateNativeOtpPending | None:
        if not isinstance(raw, str) or len(raw) > 16_384:
            return None
        try:
            data = browser_record(raw, StoredNativeOtp)
            validate_files_resource_intent(
                issuer=issuer, client_id=client_id, resource_audience=data.resource_audience
            )
            return data.pending(
                state=state, issuer=issuer, client_id=client_id, attempt_id=attempt_id
            )
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            return None

    async def claim_native_otp_start(
        self, *, state: str, issuer: str, client_id: str, method_index: int
    ) -> PrivateNativeOtpPending | None:
        if type(method_index) is not int or not 0 <= method_index <= 9:
            return None
        attempt = secrets.token_urlsafe(32)
        try:
            raw = await eval_script(
                self._storage.client,
                CLAIM_OTP_START,
                1,
                self._storage.key("native-init", state),
                issuer,
                client_id,
                method_index,
                attempt,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native OTP start claim unavailable") from None
        if not isinstance(raw, str) or len(raw) > 16_384:
            return None
        # Returned payload was BEFORE mutation: selected ID is in methods.
        try:
            data = browser_record(raw, StoredNativeOtp)
            if data.methods is None:
                return None
            data = data.model_copy(update={"selected_otp_id": data.methods[method_index].id})
            validate_files_resource_intent(
                issuer=issuer, client_id=client_id, resource_audience=data.resource_audience
            )
            return data.pending(
                state=state, issuer=issuer, client_id=client_id, attempt_id=SecretStr(attempt)
            )
        except (ValueError, TypeError, IndexError, KeyError, OverflowError, OSError):
            return None

    async def confirm_native_otp_start(
        self,
        *,
        challenge: PrivateNativeOtpPending,
        otp_code: SecretStr,
        otp_expires_at: int,
        provider_cookie: SecretStr,
        csrf_token: SecretStr,
    ) -> bool:
        if (
            challenge.selected_otp_id is None
            or challenge.login_code is None
            or not private_secret(otp_code)
            or re.fullmatch(r"[A-Za-z0-9]{48}", otp_code.get_secret_value(), re.ASCII) is None
            or type(otp_expires_at) is not int
            or not private_secret(provider_cookie)
            or not private_secret(csrf_token)
            or re.fullmatch(r"[A-Za-z0-9]{32}", csrf_token.get_secret_value(), re.ASCII) is None
        ):
            return False
        try:
            result = await eval_script(
                self._storage.client,
                CONFIRM_OTP_START,
                1,
                self._storage.key("native-init", challenge.original.state),
                challenge.attempt_id.get_secret_value(),
                otp_code.get_secret_value(),
                otp_expires_at * 1000,
                provider_cookie.get_secret_value(),
                csrf_token.get_secret_value(),
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native OTP start confirmation unavailable") from None
        return type(result) is int and result == 1

    async def claim_native_otp_finish(
        self, *, state: str, issuer: str, client_id: str
    ) -> PrivateNativeOtpPending | None:
        attempt = secrets.token_urlsafe(32)
        try:
            raw = await eval_script(
                self._storage.client,
                CLAIM_OTP_FINISH,
                1,
                self._storage.key("native-init", state),
                issuer,
                client_id,
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native OTP finish claim unavailable") from None
        return self._private_otp_pending(
            raw,
            state=state,
            issuer=issuer,
            client_id=client_id,
            attempt_id=SecretStr(attempt),
        )

    async def delete_native_init(self, *, state: str) -> None:
        """Cancel init/claim OR its completed session before clearing browser state."""
        try:
            result = await eval_script(
                self._storage.client,
                CANCEL_LOGIN,
                2,
                self._storage.key("native-init", state),
                self._storage.key("native-pow", state),
                "briareus:panel:oidc:session:",
            )
        except ValkeyError:
            raise OidcSessionStoreUnavailable("native login cancellation unavailable") from None
        if type(result) is not int or result != 1:
            raise OidcSessionStoreUnavailable("native cancellation linkage invalid")
