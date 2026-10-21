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


class BaseConnectionForm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128, title="Название подключения")
    credential: SecretStr = Field(title="Учётные данные", json_schema_extra={"writeOnly": True})
    ca_cert_pem: str = Field(default="", max_length=16384, title="Сертификат центра сертификации (PEM)")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        return ProviderOptions.clean_display_name(value)

    @field_validator("credential")
    @classmethod
    def credential_present(cls, value):
        if not 1 <= len(value.get_secret_value()) <= 32768:
            raise ValueError("Credential required")
        return value


class GitRuntimePolicyForm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False


class GitPolicyForm(GitRuntimePolicyForm):
    protected_branches: list[str] = Field(default_factory=list, max_length=64)
    required_checks: list[str] = Field(default_factory=lambda: ["test", "docker"], max_length=64)
    required_reviewers: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("protected_branches", "required_checks", "required_reviewers")
    @classmethod
    def bounded_names(cls, values):
        if any(not item.strip() or len(item) > 128 or any(ord(c) < 32 for c in item) for item in values):
            raise ValueError("Bounded non-empty policy entries required")
        return list(dict.fromkeys(item.strip() for item in values))


class GitLabPolicyForm(GitRuntimePolicyForm):
    protected_branches: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("protected_branches")
    @classmethod
    def bounded_names(cls, values):
        return GitPolicyForm.bounded_names(values)


class GitHubConnectionForm(BaseConnectionForm):
    git_policy: GitPolicyForm = Field(default_factory=GitPolicyForm, title="Политика Git")
    provider: Literal["github"]
    auth_type: Literal["github_token", "github_app"] = "github_token"
    external_id: str = Field(default="", max_length=32, title="GitHub App ID")
    base_url: Literal["https://api.github.com"] = "https://api.github.com"

    @field_validator("external_id")
    @classmethod
    def app_id(cls, value):
        if value and (not value.isascii() or not value.isdigit() or int(value) <= 0):
            raise ValueError("Numeric GitHub App ID required")
        return value


class EndpointConnectionForm(BaseConnectionForm):
    base_url: str = Field(min_length=1, max_length=2048, title="Адрес сервиса")

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value):
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


ConnectionForm = Annotated[GitHubConnectionForm | GitLabConnectionForm | SigNozConnectionForm | CoolifyConnectionForm,
                           Field(discriminator="provider")]
CONNECTION_FORM = TypeAdapter(ConnectionForm)


def validate_connection(value: dict[str, object]):
    form = CONNECTION_FORM.validate_python(value)
    secret = form.credential.get_secret_value()
    if form.provider == "github" and form.auth_type == "github_app":
        if not form.external_id:
            raise ValueError("GitHub App ID required")
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        if not isinstance(load_pem_private_key(secret.replace("\\n", "\n").encode(), None), RSAPrivateKey):
            raise ValueError("GitHub App requires an RSA PEM private key")
    elif any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise ValueError("Token contains invalid characters")
    if form.ca_cert_pem:
        import ssl
        ssl.create_default_context(cadata=form.ca_cert_pem.replace("\\n", "\n"))
    return form
