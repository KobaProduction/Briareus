from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from common.settings import ProcessSettings, _tuple_value


class GatewayAuthSettings(ProcessSettings):
    enabled: bool = Field(True, validation_alias="OAUTH_ENABLED")
    public_base_url: str = Field("", validation_alias="MCP_PUBLIC_BASE_URL")
    oauth_jwt_signing_key: str = Field("", validation_alias="MCP_OAUTH_JWT_SIGNING_KEY", repr=False)
    oauth_jwt_signing_key_file: Path | None = Field(
        None, validation_alias="MCP_OAUTH_JWT_SIGNING_KEY_FILE"
    )
    identity_issuer_url: str = Field("", validation_alias="ZITADEL_ISSUER_URL")
    allowed_subjects: Annotated[tuple[str, ...], NoDecode] = Field(
        (), validation_alias="ZITADEL_ALLOWED_SUBJECTS"
    )
    introspection_url: str = Field(
        "http://control-panel-api:8000/introspect",
        validation_alias="MCP_OAUTH_INTROSPECTION_URL",
    )
    introspection_token: str = Field(
        "", validation_alias="MCP_OAUTH_INTROSPECTION_TOKEN", repr=False
    )
    introspection_token_file: Path | None = Field(
        None, validation_alias="MCP_OAUTH_INTROSPECTION_TOKEN_FILE"
    )

    @field_validator("allowed_subjects", mode="before")
    @classmethod
    def _parse_subjects(cls, value: object) -> object:
        return _tuple_value(value)

    @property
    def resolved_signing_key(self) -> str:
        from common.identity_settings import read_secret

        return read_secret(
            self.oauth_jwt_signing_key,
            self.oauth_jwt_signing_key_file,
            setting_name="MCP_OAUTH_JWT_SIGNING_KEY",
        )

    def validate_bootstrap(self) -> None:
        if not self.enabled:
            return
        if not self.public_base_url or not self.identity_issuer_url or not self.allowed_subjects:
            raise ValueError(
                "MCP_PUBLIC_BASE_URL, ZITADEL_ISSUER_URL and ZITADEL_ALLOWED_SUBJECTS are required"
            )
        if not self.resolved_signing_key:
            raise ValueError("MCP OAuth signing key is required")
        if not self.resolved_introspection_token:
            raise ValueError("Private OAuth introspection credential is required")

    @property
    def resolved_introspection_token(self) -> str:
        from common.identity_settings import read_secret

        return read_secret(
            self.introspection_token,
            self.introspection_token_file,
            setting_name="MCP_OAUTH_INTROSPECTION_TOKEN",
        )
