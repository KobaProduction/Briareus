"""Compose only explicitly configured, same-origin Rauthy MCP audiences."""

import json
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from node_protocol.module_effects import MODULES


class McpIssuerRegistry(Protocol):
    def get(self, module: str) -> TrustedRauthyIssuerKeys | None: ...


@dataclass(frozen=True, slots=True)
class ConfiguredMcpIssuers:
    entries: tuple[tuple[str, TrustedRauthyIssuerKeys], ...]

    def get(self, module: str) -> TrustedRauthyIssuerKeys | None:
        return next((keys for name, keys in self.entries if name == module), None)


def _audiences() -> tuple[tuple[str, str], ...]:
    raw = json.loads(os.environ.get("MCP_RESOURCE_AUDIENCES", "{}"))
    if (
        not isinstance(raw, dict)
        or len(raw) > len(MODULES)
        or set(raw) - MODULES
        or any(
            not isinstance(value, str) or not value.startswith("https://") for value in raw.values()
        )
    ):
        raise ValueError("Explicit MCP resource audience map required")
    return tuple((module, audience) for module, audience in raw.items())


def _require_audience(module: str, audience: str, issuer: str) -> None:
    expected, parsed = urlsplit(issuer), urlsplit(audience)
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected.netloc
        or parsed.path != f"/hands/{module}/mcp"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Exact same-origin MCP resource audience required")


def configured_issuers() -> ConfiguredMcpIssuers:
    audiences = _audiences()
    if not audiences:
        return ConfiguredMcpIssuers(())
    issuer = os.environ["MCP_OIDC_ISSUER"]
    local_fetch = None
    if os.environ.get("MCP_LOCAL_TLS_DIAL"):
        if (
            os.environ.get("BRIAREUS_LOCAL_TESTING") != "1"
            or issuer != "https://127.0.0.1/auth/v1/"
            or os.environ["MCP_LOCAL_TLS_DIAL"] != "local-tls"
        ):
            raise ValueError("Local HTTPS dial override is restricted to the local Compose issuer")
        from authorization._local_rauthy_keys import fetch_local_issuer

        local_fetch = fetch_local_issuer
    for module, audience in audiences:
        _require_audience(module, audience, issuer)
    return ConfiguredMcpIssuers(
        tuple(
            (
                module,
                TrustedRauthyIssuerKeys(
                    issuer=issuer,
                    resource_audience=audience,
                    oauth_client_id=os.environ["MCP_OAUTH_CLIENT_ID"],
                    json_fetch=local_fetch,
                ),
            )
            for module, audience in audiences
        )
    )
