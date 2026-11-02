"""Explicit ZITADEL and BRI OAuth configuration; loaded at composition roots."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from common.settings import ProcessSettings


def read_secret(value: str, file_path: Path | None, *, setting_name: str) -> str:
    """Resolve one explicit secret source without exposing its contents."""
    if value and file_path is not None:
        raise ValueError(f"configure only {setting_name} or {setting_name}_FILE")
    if file_path is None:
        return value.strip()
    try:
        return file_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"cannot read {setting_name}_FILE") from error


def identity_origin(value: str, *, allow_local_http: bool) -> str:
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError("identity origin contains whitespace or control characters")
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("identity origin must not contain credentials, query or fragment")
    if not parsed.hostname or parsed.path not in ("", "/"):
        raise ValueError("identity origin must be an absolute origin without a path")
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1", "auth.bri.localhost")
    if parsed.scheme != "https" and not (allow_local_http and local and parsed.scheme == "http"):
        raise ValueError("identity origin requires HTTPS or explicit local-development HTTP")
    return f"{parsed.scheme}://{parsed.netloc}"


class ZitadelSettings(ProcessSettings):
    issuer_url: str = Field("", validation_alias="ZITADEL_ISSUER_URL")
    client_id: str = Field("", validation_alias="ZITADEL_CLIENT_ID")
    client_secret: str = Field("", validation_alias="ZITADEL_CLIENT_SECRET", repr=False)
    client_secret_file: Path | None = Field(None, validation_alias="ZITADEL_CLIENT_SECRET_FILE")
    allowed_subjects: Annotated[tuple[str, ...], NoDecode] = Field(
        (), validation_alias="ZITADEL_ALLOWED_SUBJECTS"
    )
    allow_local_http: bool = Field(False, validation_alias="ZITADEL_ALLOW_LOCAL_HTTP")
    request_timeout_seconds: float = Field(
        10, gt=0, le=60, validation_alias="ZITADEL_TIMEOUT_SECONDS"
    )

    @field_validator("allowed_subjects", mode="before")
    @classmethod
    def parse_subjects(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def canonical_issuer(self) -> str:
        return identity_origin(self.issuer_url, allow_local_http=self.allow_local_http)

    @property
    def discovery_url(self) -> str:
        return self.canonical_issuer + "/.well-known/openid-configuration"

    @property
    def resolved_client_secret(self) -> str:
        return read_secret(
            self.client_secret, self.client_secret_file, setting_name="ZITADEL_CLIENT_SECRET"
        )

    def validate_bootstrap(self) -> None:
        identity_origin(self.issuer_url, allow_local_http=self.allow_local_http)
        if not self.client_id or not self.resolved_client_secret or not self.allowed_subjects:
            raise ValueError(
                "ZITADEL client credentials and explicit allowed subjects are required"
            )


class McpAuthSettings(ProcessSettings):
    public_base_url: str = Field("", validation_alias="MCP_PUBLIC_BASE_URL")
    oauth_jwt_signing_key: str = Field("", validation_alias="MCP_OAUTH_JWT_SIGNING_KEY", repr=False)
    oauth_jwt_signing_key_file: Path | None = Field(
        None, validation_alias="MCP_OAUTH_JWT_SIGNING_KEY_FILE"
    )
    state_directory: Path = Field(
        Path("/var/lib/bri/oauth"), validation_alias="MCP_OAUTH_STATE_DIRECTORY"
    )
    allowed_client_redirect_uris: Annotated[tuple[str, ...], NoDecode] = Field(
        ("https://chatgpt.com/connector_platform_oauth_redirect",),
        validation_alias="MCP_OAUTH_ALLOWED_REDIRECT_URIS",
    )
    allow_local_http: bool = Field(False, validation_alias="ZITADEL_ALLOW_LOCAL_HTTP")
    introspection_token: str = Field(
        "", validation_alias="MCP_OAUTH_INTROSPECTION_TOKEN", repr=False
    )
    introspection_token_file: Path | None = Field(
        None, validation_alias="MCP_OAUTH_INTROSPECTION_TOKEN_FILE"
    )

    @field_validator("allowed_client_redirect_uris", mode="before")
    @classmethod
    def parse_redirects(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def resolved_signing_key(self) -> str:
        return read_secret(
            self.oauth_jwt_signing_key,
            self.oauth_jwt_signing_key_file,
            setting_name="MCP_OAUTH_JWT_SIGNING_KEY",
        )

    def validate_bootstrap(self) -> None:
        identity_origin(self.public_base_url, allow_local_http=self.allow_local_http)
        if not self.resolved_signing_key or not self.allowed_client_redirect_uris:
            raise ValueError("MCP OAuth signing key and allowed redirect URIs are required")
        if not self.resolved_introspection_token:
            raise ValueError("MCP OAuth private introspection credential is required")

    @property
    def resolved_introspection_token(self) -> str:
        return read_secret(
            self.introspection_token,
            self.introspection_token_file,
            setting_name="MCP_OAUTH_INTROSPECTION_TOKEN",
        )


class PanelIdentitySettings(ProcessSettings):
    public_base_url: str = Field("", validation_alias="CONTROL_PANEL_PUBLIC_BASE_URL")
    allow_local_http: bool = Field(False, validation_alias="ZITADEL_ALLOW_LOCAL_HTTP")

    @property
    def public_origin(self) -> str:
        return identity_origin(self.public_base_url, allow_local_http=self.allow_local_http)
