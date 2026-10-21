"""Typed private dispatch of original provider callables; no second MCP server."""
from inspect import isawaitable
from pydantic import ConfigDict, validate_call
from .source_tools import register_source_tools
from common.runtime_policy_contracts import GitHubRuntimePolicy, GitLabRuntimePolicy
from common.settings import GitHubPolicySettings, GitLabSettings
from modules.github.workflow_guard import SOURCE_MUTATION_TOOLS as GH_MUTATIONS
from modules.gitlab.workflow_guard import SOURCE_MUTATION_TOOLS as GL_MUTATIONS
from modules.gitlab.workflow_guard import LOCAL_GIT_TOOLS as GL_LOCAL_GIT


class SourceToolDispatch:
    def __init__(self, accounts, policies=None):
        policies = policies or {}
        self.github_policy = GitHubRuntimePolicy.model_validate(policies.get("github_runtime", {}))
        self.gitlab_policy = GitLabRuntimePolicy.model_validate(policies.get("gitlab_runtime", {}))
        self.tools = {}
        self.annotations = {}
        self.contexts = register_source_tools(self, accounts, policies)

    def tool(self, **metadata):
        def register(function):
            if function.__name__ in self.tools:
                raise ValueError("Duplicate provider tool")
            self.tools[function.__name__] = validate_call(
                config=ConfigDict(strict=True), validate_return=True)(function)
            self.annotations[function.__name__] = metadata.get("annotations")
            return function
        return register

    def configure(self, policies):
        self.github_policy = GitHubRuntimePolicy.model_validate(policies.get("github_runtime", {}))
        self.gitlab_policy = GitLabRuntimePolicy.model_validate(policies.get("gitlab_runtime", {}))
        github, gitlab = self.contexts
        github.policy = GitHubPolicySettings.model_validate(policies.get("github", {}))
        github.runtime_policy = self.github_policy
        gitlab.settings = GitLabSettings.model_validate(policies.get("gitlab", {}))

    async def call(self, name, arguments):
        if name not in self.tools:
            raise ValueError("Unregistered provider tool")
        if ((name in GH_MUTATIONS and not self.github_policy.remote_source_mutations_enabled)
            or (name in GL_MUTATIONS and not self.gitlab_policy.remote_source_mutations_enabled)
            or (name in (GL_LOCAL_GIT | {"create_worktree", "checkout_repository"}) and not self.gitlab_policy.local_git_transport_enabled)
            or (name in {"github_authorize_local_git", "github_push_local_git", "github_create_worktree", "github_checkout_repository"}
                and not self.github_policy.local_git_transport_enabled)):
            raise ValueError("Remote source mutation or local Git disabled by current owner policy")
        result = self.tools[name](**arguments)
        return await result if isawaitable(result) else result

    def clear(self):
        for context in self.contexts:
            clear = getattr(context, "clear", None)
            if clear is not None:
                clear()
        self.contexts = ()
        self.tools.clear()
        self.annotations.clear()
