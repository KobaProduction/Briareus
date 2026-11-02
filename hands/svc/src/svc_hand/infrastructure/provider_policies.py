"""Adapt the current custody policy record to existing provider policy settings."""

from dataclasses import dataclass

from common.settings import GitHubPolicySettings, GitLabSettings
from node_protocol.provider_context import InvocationPolicies
from service_runtime.runtime_policy_contracts import GitHubRuntimePolicy, GitLabRuntimePolicy


@dataclass(frozen=True, slots=True)
class SourceProviderPolicies:
    github: GitHubPolicySettings
    gitlab: GitLabSettings
    github_runtime: GitHubRuntimePolicy
    gitlab_runtime: GitLabRuntimePolicy

    @classmethod
    def from_context(cls, policies: InvocationPolicies | None) -> "SourceProviderPolicies":
        if policies is None:
            return cls(
                GitHubPolicySettings(),
                GitLabSettings(),
                GitHubRuntimePolicy(),
                GitLabRuntimePolicy(),
            )
        for name, policy in (
            ("github", policies.github),
            ("gitlab", policies.gitlab),
            ("github_runtime", policies.github_runtime),
            ("gitlab_runtime", policies.gitlab_runtime),
        ):
            if name in policies.model_fields_set and policy is None:
                raise ValueError("Concrete current provider policy required")
        return cls(
            GitHubPolicySettings.model_validate(policies.github, from_attributes=True)
            if policies.github is not None
            else GitHubPolicySettings(),
            GitLabSettings.model_validate(policies.gitlab, from_attributes=True)
            if policies.gitlab is not None
            else GitLabSettings(),
            GitHubRuntimePolicy.model_validate(policies.github_runtime, from_attributes=True)
            if policies.github_runtime is not None
            else GitHubRuntimePolicy(),
            GitLabRuntimePolicy.model_validate(policies.gitlab_runtime, from_attributes=True)
            if policies.gitlab_runtime is not None
            else GitLabRuntimePolicy(),
        )
