from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from briareus_environment_models import ProcessSettings
from briareus_environment_parsing import parse_csv_tuple
from pydantic import Field, field_validator
from pydantic_settings import NoDecode


class ZitadelTokenSettings(ProcessSettings):
    issuer_url: str = Field("", validation_alias="ZITADEL_ISSUER_URL")
    project_id: str = Field("", validation_alias="ZITADEL_PROJECT_ID")
    organization_id: str = Field("", validation_alias="ZITADEL_ORGANIZATION_ID")
    audience: str = Field("", validation_alias="ZITADEL_AUDIENCE")
    algorithms: Annotated[tuple[str, ...], NoDecode] = Field(
        ("RS256",), validation_alias="ZITADEL_JWT_ALGORITHMS"
    )

    @field_validator("algorithms", mode="before")
    @classmethod
    def _algorithms(cls, value: object) -> object:
        return parse_csv_tuple(value)

    @property
    def resolved_audience(self) -> str:
        return self.audience or self.project_id

    @property
    def audience_scope(self) -> str:
        return f"urn:zitadel:iam:org:project:id:{self.project_id}:aud"

    @property
    def roles_claim(self) -> str:
        return f"urn:zitadel:iam:org:project:{self.project_id}:roles"

    @property
    def authorization_scopes(self) -> tuple[str, ...]:
        return ("openid", "profile", self.audience_scope, "urn:zitadel:iam:org:projects:roles")

    def validate_bootstrap(self) -> None:
        if not all((self.issuer_url, self.project_id, self.organization_id)):
            raise ValueError("ZITADEL issuer, project and organization are required")
        parsed = urlsplit(self.issuer_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} or (
            parsed.hostname is not None and parsed.hostname.endswith(".localhost")
        )
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("ZITADEL issuer must use HTTPS (HTTP is allowed for localhost tests)")
        if (
            not parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("ZITADEL issuer must be an absolute issuer URL without credentials")
        if not self.algorithms or not set(self.algorithms) <= {
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "EdDSA",
        }:
            raise ValueError("ZITADEL JWT algorithms must be an explicit asymmetric allowlist")
        if self.resolved_audience != self.project_id:
            raise ValueError("ZITADEL audience must identify the configured Briareus project")
