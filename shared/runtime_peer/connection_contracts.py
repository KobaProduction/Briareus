"""Stable public provider configuration on the Control Panel API → Resources boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime_peer.domain.git_policy import checked_policy_names


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
    def bounded_names(cls, values: list[str]) -> list[str]:
        return list(checked_policy_names(tuple(values)))


class GitLabPolicyForm(GitRuntimePolicyForm):
    protected_branches: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("protected_branches")
    @classmethod
    def bounded_names(cls, values: list[str]) -> list[str]:
        return GitPolicyForm.bounded_names(values)


class ConnectionConfigurationInput(BaseModel):
    """Public provider fields; credentials remain in the separate secret input."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    provider: Literal["github", "gitlab", "signoz", "coolify"]
    auth_type: str | None = None
    base_url: str | None = None
    ca_cert_pem: str = ""
    external_id: str | None = None
    git_policy: GitPolicyForm | GitLabPolicyForm | None = None


def _configuration_input(value: object) -> ConnectionConfigurationInput | None:
    if value == {}:
        return None
    if value is None:
        raise ValueError("Connection configuration must be an object")
    return ConnectionConfigurationInput.model_validate(value)
