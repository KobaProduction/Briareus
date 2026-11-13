"""RFC 7662 resource-server validation against the configured external provider."""

from __future__ import annotations

import json
import time
from urllib.parse import quote_plus

import httpx
from briareus_json_values import JsonObject, json_object
from pydantic import BaseModel, ConfigDict

from .discovery import discover
from .settings import OidcTokenSettings, secure_provider_url


class InactiveAccessToken(ValueError):
    """Provider confirmed that an access token is inactive."""


class _Status(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    active: bool


class ProviderIntrospection:
    def __init__(self, settings: OidcTokenSettings) -> None:
        self._settings = settings
        self._endpoint = ""
        self._expires = 0.0

    def _url(self) -> str:
        if time.monotonic() >= self._expires:
            metadata = discover(self._settings.issuer_url)
            self._endpoint = secure_provider_url(metadata.introspection_endpoint)
            self._expires = time.monotonic() + 300
        return self._endpoint

    def verify(self, token: str) -> JsonObject:
        auth = httpx.BasicAuth(
            quote_plus(self._settings.introspection_client_id),
            quote_plus(self._settings.introspection_client_secret.get_secret_value()),
        )
        with httpx.stream(
            "POST",
            self._url(),
            auth=auth,
            data={"token": token, "token_type_hint": "access_token"},
            timeout=5,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 65536:
                    raise ValueError("OIDC introspection response exceeds the size limit")
        status = _Status.model_validate_json(bytes(content))
        if not status.active:
            raise InactiveAccessToken("Inactive OIDC access token")
        return json_object(json.loads(content))
