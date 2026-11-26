"""Bounded private Gateway client; no provider endpoint, keys or secret in API."""

from __future__ import annotations

import httpx
from briareus_oidc import TokenAccessDenied, TokenVerificationError, VerifiedPrincipal
from briareus_oidc.gateway_contract import (
    INTERNAL_HOST,
    INTERNAL_ORIGIN,
    MAX_MESSAGE_BYTES,
    METADATA_PATH,
    VERIFY_PATH,
    GatewayIdentityUnavailable,
    GatewayMetadata,
    PrincipalMessage,
    VerifyRequest,
)


def _check_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        if response.headers.get("WWW-Authenticate"):
            raise GatewayIdentityUnavailable("Gateway service authentication rejected")
        raise TokenVerificationError
    if response.status_code == 403:
        raise TokenAccessDenied
    if response.status_code != 200:
        raise GatewayIdentityUnavailable("Gateway identity unavailable")


def _read(response: httpx.Response) -> bytes:
    data = bytearray()
    for chunk in response.iter_bytes():
        data.extend(chunk)
        if len(data) > MAX_MESSAGE_BYTES:
            raise GatewayIdentityUnavailable("Oversized Gateway identity response")
    return bytes(data)


async def _read_async(response: httpx.Response) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > MAX_MESSAGE_BYTES:
            raise GatewayIdentityUnavailable("Oversized Gateway identity response")
    return bytes(data)


class GatewayIdentityClient:
    def __init__(self, service_token: str, *, origin: str = INTERNAL_ORIGIN) -> None:
        if not service_token.strip():
            raise ValueError("Private service authentication is required")
        headers = {"Host": INTERNAL_HOST, "Authorization": "Bearer " + service_token}
        self._sync = httpx.Client(
            base_url=origin,
            headers=headers,
            follow_redirects=False,
            trust_env=False,
            timeout=8,
        )
        self._async = httpx.AsyncClient(
            base_url=origin,
            headers=headers,
            follow_redirects=False,
            trust_env=False,
            timeout=8,
        )
        self._metadata: GatewayMetadata | None = None

    def bootstrap(self) -> GatewayMetadata:
        try:
            with self._sync.stream("GET", METADATA_PATH) as response:
                if response.status_code != 200:
                    raise GatewayIdentityUnavailable("Gateway metadata unavailable")
                self._metadata = GatewayMetadata.model_validate_json(_read(response))
                return self._metadata
        except (httpx.HTTPError, ValueError):
            raise GatewayIdentityUnavailable("Gateway metadata unavailable") from None

    def _node(self) -> str:
        if self._metadata is None:
            raise GatewayIdentityUnavailable("Gateway metadata not initialized")
        return self._metadata.node_id

    def verify(self, token: str) -> VerifiedPrincipal:
        node = self._node()
        try:
            if not token or len(token) > 16384:
                raise TokenVerificationError
            payload = VerifyRequest(token=token).model_dump()
            with self._sync.stream("POST", VERIFY_PATH, json=payload) as response:
                _check_status(response)
                return PrincipalMessage.model_validate_json(_read(response)).principal(node)
        except (TokenVerificationError, GatewayIdentityUnavailable):
            raise
        except (httpx.HTTPError, ValueError):
            raise GatewayIdentityUnavailable("Gateway verification unavailable") from None

    async def verify_async(self, token: str) -> VerifiedPrincipal:
        node = self._node()
        try:
            if not token or len(token) > 16384:
                raise TokenVerificationError
            payload = VerifyRequest(token=token).model_dump()
            async with self._async.stream("POST", VERIFY_PATH, json=payload) as response:
                _check_status(response)
                return PrincipalMessage.model_validate_json(await _read_async(response)).principal(
                    node
                )
        except (TokenVerificationError, GatewayIdentityUnavailable):
            raise
        except (httpx.HTTPError, ValueError):
            raise GatewayIdentityUnavailable("Gateway verification unavailable") from None

    async def close(self) -> None:
        self._sync.close()
        await self._async.aclose()
