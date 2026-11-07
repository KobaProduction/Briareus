from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from briareus_environment_models import ProcessSettings
from briareus_environment_parsing import parse_csv_tuple
from pydantic import Field, field_validator
from pydantic_settings import NoDecode


def secure_provider_url(value: str) -> str:
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} or (
        parsed.hostname is not None and parsed.hostname.endswith(".localhost")
    )
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("OIDC endpoints require HTTPS, except localhost test endpoints")
    if not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError(
            "OIDC endpoints must be absolute URLs without credentials, query or fragment"
        )
    if value != value.strip():
        raise ValueError("OIDC endpoints must not contain surrounding whitespace")
    return value


class OidcTokenSettings(ProcessSettings):
    issuer_url: str = Field("", validation_alias="OIDC_ISSUER_URL")
    audience: str = Field("", validation_alias="OIDC_AUDIENCE")
    algorithms: Annotated[tuple[str, ...], NoDecode] = Field(
        ("RS256",), validation_alias="OIDC_JWT_ALGORITHMS"
    )
    authorization_scopes: Annotated[tuple[str, ...], NoDecode] = Field(
        ("openid", "profile", "email", "offline_access"), validation_alias="OIDC_SCOPES"
    )
    roles_claim_path: tuple[str, ...] = Field(("roles",), validation_alias="OIDC_ROLES_CLAIM_PATH")
    roles_format: Literal["list", "organization_grants"] = Field(
        "list", validation_alias="OIDC_ROLES_FORMAT"
    )
    roles_organization_id: str = Field("", validation_alias="OIDC_ROLES_ORGANIZATION_ID")
    required_role: str = Field("", validation_alias="OIDC_REQUIRED_ROLE")

    @field_validator("algorithms", "authorization_scopes", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return parse_csv_tuple(value)

    @property
    def resolved_audience(self) -> str:
        return self.audience

    def validate_bootstrap(self) -> None:
        secure_provider_url(self.issuer_url)
        if not self.audience.strip() or self.audience != self.audience.strip():
            raise ValueError(
                "OIDC_AUDIENCE must identify the protected API separately from the panel client"
            )
        if not self.algorithms or not set(self.algorithms) <= {
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "EdDSA",
        }:
            raise ValueError("OIDC JWT algorithms must be an explicit asymmetric allowlist")
        if "openid" not in self.authorization_scopes:
            raise ValueError("OIDC_SCOPES must include openid")
        if (
            not self.roles_claim_path
            or not all(self.roles_claim_path)
            or not self.required_role.strip()
            or self.required_role != self.required_role.strip()
        ):
            raise ValueError("OIDC role claim path and required application role must be explicit")
        if self.roles_format == "organization_grants" and not self.roles_organization_id:
            raise ValueError("Organization-scoped grants require OIDC_ROLES_ORGANIZATION_ID")
