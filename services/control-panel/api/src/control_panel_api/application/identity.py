"""Panel authorization delegates token authority to the configured external OIDC provider."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from briareus_environment_models import ProcessSettings
from briareus_oidc import OidcTokenVerifier, VerifiedPrincipal
from pydantic import Field


class PanelOidcSettings(ProcessSettings):
    public_base_url: str = Field("", validation_alias="CONTROL_PANEL_PUBLIC_BASE_URL")
    client_id: str = Field("", validation_alias="OIDC_PANEL_CLIENT_ID")
    allow_local_http: bool = Field(False, validation_alias="OIDC_ALLOW_LOCAL_HTTP")

    @property
    def public_origin(self) -> str:
        parsed = urlsplit(self.public_base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        valid_scheme = parsed.scheme == "https" or (
            self.allow_local_http and local and parsed.scheme == "http"
        )
        if (
            not valid_scheme
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or self.public_base_url != self.public_base_url.strip()
        ):
            raise ValueError("CONTROL_PANEL_PUBLIC_BASE_URL must be a secure origin")
        return f"{parsed.scheme}://{parsed.netloc}"

    def validate_bootstrap(self) -> None:
        _origin = self.public_origin
        if not self.client_id:
            raise ValueError("OIDC_PANEL_CLIENT_ID is required")


@dataclass(frozen=True)
class PanelTokenIdentity:
    verifier: OidcTokenVerifier
    oidc: PanelOidcSettings
    issuer: str
    audience: str

    def __post_init__(self) -> None:
        if self.audience == self.oidc.client_id:
            raise ValueError("OIDC API audience must differ from the public panel client ID")

    def verify(self, token: str) -> VerifiedPrincipal:
        return self.verifier.verify(token)

    async def verify_async(self, token: str) -> VerifiedPrincipal:
        return await self.verifier.verify_async(token)
