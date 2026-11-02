"""GitHub App permission names and levels from the provider REST schema.

Source: github/rest-api-description, app-permissions. These are provider facts,
not Briareus authorization grants. Unreported fields remain absent on the wire.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .requests import omit_unreported


class AppPermissions(BaseModel):
    actions: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    administration: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    artifact_metadata: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    attestations: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    checks: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    code_quality: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    codespaces: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    contents: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    dependabot_secrets: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    deployments: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    discussions: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    environments: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    issues: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    merge_queues: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    metadata: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    packages: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    pages: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    pull_requests: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    repository_custom_properties: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    repository_hooks: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    repository_projects: Literal["read", "write", "admin"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    secret_scanning_alerts: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    secrets: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    security_events: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    single_file: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    statuses: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    vulnerability_alerts: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    workflows: Literal["write"] | None = Field(default=None, exclude_if=omit_unreported)
    custom_properties_for_organizations: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    members: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    organization_administration: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_custom_roles: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_custom_org_roles: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_custom_properties: Literal["read", "write", "admin"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_copilot_seat_management: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_copilot_agent_settings: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_copilot_requests: Literal["read"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_external_properties_for_repos: Literal["read", "write", "admin"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_announcement_banners: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_events: Literal["read"] | None = Field(default=None, exclude_if=omit_unreported)
    organization_hooks: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_personal_access_tokens: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_personal_access_token_requests: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_plan: Literal["read"] | None = Field(default=None, exclude_if=omit_unreported)
    organization_projects: Literal["read", "write", "admin"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_packages: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_secrets: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_self_hosted_runners: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    organization_user_blocking: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    email_addresses: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    followers: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    git_ssh_keys: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    gpg_keys: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    interaction_limits: Literal["read", "write"] | None = Field(
        default=None, exclude_if=omit_unreported
    )
    profile: Literal["write"] | None = Field(default=None, exclude_if=omit_unreported)
    starring: Literal["read", "write"] | None = Field(default=None, exclude_if=omit_unreported)
    enterprise_custom_properties_for_organizations: Literal["read", "write", "admin"] | None = (
        Field(default=None, exclude_if=omit_unreported)
    )
