"""FastAPI connection forms ported from the HTTP Bridge repair branch.

Source: repair/legacy-mcp-bridge-e41085d b89c5f6,
src/management/domain/accounts.py and infrastructure/provider_checks.py.
Provider/auth combinations and App ID semantics are preserved. Current
Resources custody, HTTPS verification and the Coolify Dev fence apply.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, field_validator

from projects._provider_registry import ProviderOptions
from projects.domain.connection_settings import (
    ConnectionSettings,
)
from projects.infrastructure.connection_policy_codec import policy_record
from runtime_peer.connection_contracts import ConnectionConfigurationInput
from runtime_peer.connection_contracts import GitLabPolicyForm as GitLabPolicyForm
from runtime_peer.connection_contracts import GitPolicyForm as GitPolicyForm
from runtime_peer.connection_contracts import GitRuntimePolicyForm as GitRuntimePolicyForm


class BaseConnectionForm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128, title="Название подключения")
    credential: SecretStr = Field(title="Учётные данные", json_schema_extra={"writeOnly": True})
    ca_cert_pem: str = Field(
        default="", max_length=16384, title="Сертификат центра сертификации (PEM)"
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return ProviderOptions.clean_display_name(value)

    @field_validator("credential")
    @classmethod
    def credential_present(cls, value: SecretStr) -> SecretStr:
        if not 1 <= len(value.get_secret_value()) <= 32768:
            raise ValueError("Credential required")
        return value


class GitHubConnectionForm(BaseConnectionForm):
    git_policy: GitPolicyForm = Field(default_factory=GitPolicyForm, title="Политика Git")
    provider: Literal["github"]
    auth_type: Literal["github_token", "github_app"] = "github_token"
    external_id: str = Field(default="", max_length=32, title="GitHub App ID")
    base_url: Literal["https://api.github.com"] = "https://api.github.com"

    @field_validator("external_id")
    @classmethod
    def app_id(cls, value: str) -> str:
        if value and (not value.isascii() or not value.isdigit() or int(value) <= 0):
            raise ValueError("Numeric GitHub App ID required")
        return value


class EndpointConnectionForm(BaseConnectionForm):
    base_url: str = Field(min_length=1, max_length=2048, title="Адрес сервиса")

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value: str) -> str:
        return ProviderOptions.safe_url(value)


class GitLabConnectionForm(EndpointConnectionForm):
    git_policy: GitLabPolicyForm = Field(default_factory=GitLabPolicyForm, title="Политика Git")
    provider: Literal["gitlab"]
    auth_type: Literal["private_token", "bearer", "job_token"] = "private_token"
    base_url: str = "https://gitlab.com"


class SigNozConnectionForm(EndpointConnectionForm):
    provider: Literal["signoz"]
    auth_type: Literal["signoz_api_key"] = "signoz_api_key"


class CoolifyConnectionForm(EndpointConnectionForm):
    provider: Literal["coolify"]
    auth_type: Literal["coolify_api_token"] = "coolify_api_token"


ConnectionForm = Annotated[
    GitHubConnectionForm | GitLabConnectionForm | SigNozConnectionForm | CoolifyConnectionForm,
    Field(discriminator="provider"),
]
CONNECTION_FORM: TypeAdapter[ConnectionForm] = TypeAdapter(ConnectionForm)


def connection_settings(form: ConnectionForm) -> ConnectionSettings:
    policy = (
        policy_record(form.git_policy)
        if isinstance(form, (GitHubConnectionForm, GitLabConnectionForm))
        else None
    )
    return ConnectionSettings(
        name=form.name,
        provider=form.provider,
        auth_type=form.auth_type,
        base_url=form.base_url,
        ca_cert_pem=form.ca_cert_pem,
        external_id=form.external_id if isinstance(form, GitHubConnectionForm) else None,
        git_policy=policy,
    )


def validate_connection(
    configuration: ConnectionConfigurationInput, credential: SecretStr
) -> ConnectionForm:
    form = CONNECTION_FORM.validate_python(
        {**configuration.model_dump(mode="json", exclude_unset=True), "credential": credential}
    )
    secret = form.credential.get_secret_value()
    if form.provider == "github" and form.auth_type == "github_app":
        if not form.external_id:
            raise ValueError("GitHub App ID required")
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        if not isinstance(
            load_pem_private_key(secret.replace("\\n", "\n").encode(), None), RSAPrivateKey
        ):
            raise ValueError("GitHub App requires an RSA PEM private key")
    elif any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise ValueError("Token contains invalid characters")
    if form.ca_cert_pem:
        import ssl

        ssl.create_default_context(cadata=form.ca_cert_pem.replace("\\n", "\n"))
    return form
