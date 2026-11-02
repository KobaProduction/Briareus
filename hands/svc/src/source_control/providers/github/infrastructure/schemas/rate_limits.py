"""Named rate-limit families from GitHub's rate-limit-overview schema."""

from pydantic import BaseModel, Field

from .requests import omit_unreported


class RateLimitCounter(BaseModel):
    limit: int
    remaining: int
    reset: int
    used: int


class RateLimitResources(BaseModel):
    core: RateLimitCounter
    search: RateLimitCounter
    graphql: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    code_search: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    source_import: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    integration_manifest: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    actions_runner_registration: RateLimitCounter | None = Field(
        default=None, exclude_if=omit_unreported
    )
    scim: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    dependency_snapshots: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    dependency_sbom: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    code_scanning_autofix: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    copilot_usage_records: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)
    code_scanning_upload: RateLimitCounter | None = Field(default=None, exclude_if=omit_unreported)


class ProviderRateLimits(BaseModel):
    resources: RateLimitResources
    rate: RateLimitCounter
