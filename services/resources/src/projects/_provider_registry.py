"""Provider schema binding and endpoint validation for the selected Catalog layout."""

from __future__ import annotations

from pydantic import field_validator

from projects.catalog.infrastructure.provider_validation import GitHubOptions as _GitHubOptions
from projects.catalog.infrastructure.provider_validation import GitLabOptions as _GitLabOptions
from projects.catalog.infrastructure.provider_validation import (
    InfrastructureOptions as _InfrastructureOptions,
)
from projects.catalog.infrastructure.provider_validation import (
    ProviderDefinition as ProviderDefinition,
)
from projects.catalog.infrastructure.provider_validation import ProviderOptions as _ProviderOptions
from projects.catalog.infrastructure.provider_validation import _ProviderRegistry
from projects.domain.provider_endpoints import ProviderEndpoint, provider_display_name


class ProviderOptions(_ProviderOptions):
    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        return provider_display_name(value)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        return ProviderEndpoint(value).value


class GitHubOptions(_GitHubOptions, ProviderOptions):
    pass


class GitLabOptions(_GitLabOptions, ProviderOptions):
    pass


class InfrastructureOptions(_InfrastructureOptions, ProviderOptions):
    pass


_REGISTRY = {
    "github": ProviderDefinition(
        "github", frozenset({"personal_token", "github_app"}), GitHubOptions
    ),
    "gitlab": ProviderDefinition("gitlab", frozenset({"personal_token", "oauth"}), GitLabOptions),
    "coolify": ProviderDefinition("coolify", frozenset({"api_token"}), InfrastructureOptions),
    "signoz": ProviderDefinition("signoz", frozenset({"api_token"}), InfrastructureOptions),
    "grafana": ProviderDefinition("grafana", frozenset({"api_token"}), InfrastructureOptions),
    "zoomies": ProviderDefinition("zoomies", frozenset({"api_token"}), InfrastructureOptions),
}


_provider_registry = _ProviderRegistry(_REGISTRY)
provider_names = _provider_registry.provider_names
provider_auth_types = _provider_registry.provider_auth_types
validate_provider = _provider_registry.validate_provider
