"""Catalog provider schemas and typed validation over a local schema registry."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from common.platform_errors import InvalidInput
from runtime_peer.domain.provider_settings import OMITTED, ProviderSettings
from runtime_peer.provider_settings import ProviderSettingsInput


class ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    base_url: str = ""
    display_name: str = Field(default="", max_length=128)


class GitHubOptions(ProviderOptions):
    installation_id: int | None = Field(default=None, gt=0)
    organization: str = Field(default="", max_length=128)

    @field_validator("organization")
    @classmethod
    def validate_org(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", value):
            raise ValueError("organization must be a GitHub organization slug")
        return value


class GitLabOptions(ProviderOptions):
    namespace: str = Field(default="", max_length=128)

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", value):
            raise ValueError("namespace must contain only GitLab namespace segments")
        return value


class InfrastructureOptions(ProviderOptions):
    tenant: str = Field(default="", max_length=128)

    @field_validator("tenant")
    @classmethod
    def validate_tenant(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
            raise ValueError("tenant must be a platform identifier")
        return value


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider: str
    auth_types: frozenset[str]
    schema: type[ProviderOptions]


class _ProviderRegistry:
    def __init__(self, registry: Mapping[str, ProviderDefinition]) -> None:
        self._registry = registry

    def provider_names(self) -> tuple[str, ...]:
        return tuple(self._registry)

    def provider_auth_types(self, provider: str) -> tuple[str, ...]:
        definition = self._registry.get(provider.strip().casefold())
        if definition is None:
            raise InvalidInput("unsupported provider")
        return tuple(sorted(definition.auth_types))

    def validate_provider(
        self, provider: str, auth_type: str, options: ProviderSettings
    ) -> ProviderSettings:
        name = provider.strip().casefold()
        definition = self._registry.get(name)
        if definition is None or auth_type not in definition.auth_types:
            raise InvalidInput("unsupported provider authentication configuration")
        try:
            validated = definition.schema.model_validate(
                ProviderSettingsInput.from_record(options).model_dump(mode="python")
            )
        except (ValidationError, ValueError):
            # Do not copy raw input/ValidationError, which may embed secrets.
            raise InvalidInput("invalid provider-specific configuration") from None
        if (
            name == "github"
            and auth_type == "github_app"
            and (not isinstance(validated, GitHubOptions) or validated.installation_id is None)
        ):
            raise InvalidInput("GitHub App configuration requires installation_id")
        return ProviderSettings(
            base_url=validated.base_url,
            display_name=validated.display_name,
            installation_id=validated.installation_id
            if isinstance(validated, GitHubOptions)
            else OMITTED,
            organization=validated.organization
            if isinstance(validated, GitHubOptions)
            else OMITTED,
            namespace=validated.namespace if isinstance(validated, GitLabOptions) else OMITTED,
            tenant=validated.tenant if isinstance(validated, InfrastructureOptions) else OMITTED,
        )
