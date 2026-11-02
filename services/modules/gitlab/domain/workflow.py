"""Local-first policy decisions independent of MCP middleware."""

from dataclasses import dataclass

LOCAL_FIRST_GUIDANCE = (
    "Koba GitLab workflow: for substantial source changes, prefer one local-first cycle: "
    "checkout with mode='git' into the persistent Terminal workspace, edit and validate locally, "
    "commit locally, authorize the checkout, then publish once with push_local_git and open "
    "a merge "
    "request. Avoid repeated per-file GitLab API mutations; issues, merge requests, notes and "
    "pipelines remain control-plane operations."
)

REMOTE_SOURCE_MUTATION_DISABLED = (
    "Remote GitLab source/history mutations are disabled by policy. Use checkout_repository with "
    "mode='git', perform source work in Terminal, authorize_local_git, and publish with "
    "push_local_git. Issues, merge requests, notes and pipeline controls remain available."
)

LOCAL_GIT_DISABLED = (
    "Local Git transport is disabled by policy. Enable it in Version Control → GitLab → Settings "
    "before authorizing or pushing a local checkout."
)

SOURCE_MUTATION_TOOLS = frozenset(
    {
        "put_file",
        "delete_file",
        "commit_actions",
        "create_branch",
        "delete_branch",
    }
)

LOCAL_GIT_TOOLS = frozenset({"authorize_local_git", "push_local_git"})

GUIDANCE_TOOLS = SOURCE_MUTATION_TOOLS | LOCAL_GIT_TOOLS | {"checkout_repository"}


@dataclass(frozen=True, slots=True)
class SourceWorkflowPolicy:
    local_first_guidance: bool
    local_git_transport_enabled: bool
    remote_source_mutations_enabled: bool

    def description_prefix(self, tool_name: str) -> str:
        if tool_name in LOCAL_GIT_TOOLS and not self.local_git_transport_enabled:
            return LOCAL_GIT_DISABLED + " "
        if tool_name == "checkout_repository" and self.local_first_guidance:
            return (
                "Preferred entry point for substantial source work. Use mode='git', continue in "
                "Terminal, then authorize and push the local checkout. "
            )
        if tool_name in SOURCE_MUTATION_TOOLS:
            if not self.remote_source_mutations_enabled:
                return REMOTE_SOURCE_MUTATION_DISABLED + " "
            if self.local_first_guidance:
                return LOCAL_FIRST_GUIDANCE + " "
        return ""

    def denial(self, tool_name: str) -> str | None:
        if tool_name in SOURCE_MUTATION_TOOLS and not self.remote_source_mutations_enabled:
            return REMOTE_SOURCE_MUTATION_DISABLED
        if tool_name in LOCAL_GIT_TOOLS and not self.local_git_transport_enabled:
            return LOCAL_GIT_DISABLED
        return None

    def adds_guidance(self, tool_name: str) -> bool:
        return self.local_first_guidance and tool_name in GUIDANCE_TOOLS
