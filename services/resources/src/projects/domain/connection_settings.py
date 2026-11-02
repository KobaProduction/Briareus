"""Credential-free provider configuration and immutable Git policy values."""

from dataclasses import dataclass

from projects.domain.provider_endpoints import ProviderEndpoint, provider_display_name
from runtime_peer.domain.git_policy import checked_policy_names


@dataclass(frozen=True, slots=True)
class GitRuntimeConfiguration:
    local_first_guidance: bool = True
    local_git_transport_enabled: bool = True
    remote_source_mutations_enabled: bool = False
    protected_branches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(
            type(flag) is not bool
            for flag in (
                self.local_first_guidance,
                self.local_git_transport_enabled,
                self.remote_source_mutations_enabled,
            )
        ):
            raise ValueError("Boolean Git runtime policy required")
        object.__setattr__(
            self, "protected_branches", checked_policy_names(self.protected_branches)
        )


@dataclass(frozen=True, slots=True)
class GitHubConfiguration(GitRuntimeConfiguration):
    required_checks: tuple[str, ...] = ("test", "docker")
    required_reviewers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        GitRuntimeConfiguration.__post_init__(self)
        object.__setattr__(self, "required_checks", checked_policy_names(self.required_checks))
        object.__setattr__(
            self, "required_reviewers", checked_policy_names(self.required_reviewers)
        )


@dataclass(frozen=True, slots=True)
class ConnectionSettings:
    name: str
    provider: str
    auth_type: str
    base_url: str = ""
    ca_cert_pem: str = ""
    external_id: str | None = None
    git_policy: GitHubConfiguration | GitRuntimeConfiguration | None = None

    def __post_init__(self) -> None:
        provider_display_name(self.name)
        object.__setattr__(self, "base_url", ProviderEndpoint(self.base_url).value)
