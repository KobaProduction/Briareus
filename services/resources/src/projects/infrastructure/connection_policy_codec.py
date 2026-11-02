"""Resource-local conversion between stable Git policy wire values and domain facts."""

from projects.domain.connection_settings import GitHubConfiguration, GitRuntimeConfiguration
from runtime_peer.connection_contracts import GitLabPolicyForm, GitPolicyForm


def policy_record(policy: GitPolicyForm | GitLabPolicyForm) -> GitRuntimeConfiguration:
    if isinstance(policy, GitPolicyForm):
        return GitHubConfiguration(
            local_first_guidance=policy.local_first_guidance,
            local_git_transport_enabled=policy.local_git_transport_enabled,
            remote_source_mutations_enabled=policy.remote_source_mutations_enabled,
            protected_branches=tuple(policy.protected_branches),
            required_checks=tuple(policy.required_checks),
            required_reviewers=tuple(policy.required_reviewers),
        )
    return GitRuntimeConfiguration(
        local_first_guidance=policy.local_first_guidance,
        local_git_transport_enabled=policy.local_git_transport_enabled,
        remote_source_mutations_enabled=policy.remote_source_mutations_enabled,
        protected_branches=tuple(policy.protected_branches),
    )


def policy_form(policy: GitRuntimeConfiguration) -> GitPolicyForm | GitLabPolicyForm:
    if isinstance(policy, GitHubConfiguration):
        return GitPolicyForm(
            local_first_guidance=policy.local_first_guidance,
            local_git_transport_enabled=policy.local_git_transport_enabled,
            remote_source_mutations_enabled=policy.remote_source_mutations_enabled,
            protected_branches=list(policy.protected_branches),
            required_checks=list(policy.required_checks),
            required_reviewers=list(policy.required_reviewers),
        )
    return GitLabPolicyForm(
        local_first_guidance=policy.local_first_guidance,
        local_git_transport_enabled=policy.local_git_transport_enabled,
        remote_source_mutations_enabled=policy.remote_source_mutations_enabled,
        protected_branches=list(policy.protected_branches),
    )
