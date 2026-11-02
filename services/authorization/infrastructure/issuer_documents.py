"""Bounded HTTPS issuer documents; no bearer-selected URLs or redirects."""

from __future__ import annotations

import http.client
import ssl
from collections.abc import Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from authorization.domain.rauthy import RauthyKeysUnavailable
from authorization.infrastructure.authority_json import load_authority_json


def authority_document[DocumentT: BaseModel](payload: bytes, schema: type[DocumentT]) -> DocumentT:
    try:
        decoded = load_authority_json(payload)
        if not isinstance(decoded, Mapping):
            raise ValueError("Issuer document must be an object")
        return schema.model_validate_json(payload)
    except (ValueError, UnicodeError, ValidationError) as exc:
        raise RauthyKeysUnavailable("Rauthy issuer returned invalid JSON object") from exc


def read_json_https(url: str, *, max_bytes: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RauthyKeysUnavailable("Rauthy issuer HTTPS required")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RauthyKeysUnavailable("Rauthy issuer exact HTTPS resource required")
    # HTTPSConnection uses CA validation directly, without ambient proxy routing.
    # Redirects remain non-success responses and are never followed.
    client = http.client.HTTPSConnection(
        parsed.netloc,
        timeout=5.0,
        context=ssl.create_default_context(),
    )
    try:
        client.request("GET", parsed.path or "/", headers={"Accept": "application/json"})
        response = client.getresponse()
        if response.status != 200:
            raise RauthyKeysUnavailable("Rauthy issuer returned non-success")
        if response.headers.get_content_type() not in {
            "application/json",
            "application/jwk-set+json",
        }:
            raise RauthyKeysUnavailable("Rauthy keys response is not JSON")
        payload = response.read(max_bytes + 1)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise RauthyKeysUnavailable("Rauthy issuer HTTPS fetch unavailable") from exc
    finally:
        client.close()
    if len(payload) > max_bytes:
        raise RauthyKeysUnavailable("Rauthy issuer response exceeded byte limit")
    return payload
