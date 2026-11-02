from service_runtime.runtime_policy_contracts import GitHubRuntimePolicy as GitHubRuntimePolicy
from source_control.providers.github.workflow_guard import GUIDANCE_TOOLS as GUIDANCE_TOOLS
from source_control.providers.github.workflow_guard import (
    REMOTE_SOURCE_MUTATION_DISABLED as REMOTE_SOURCE_MUTATION_DISABLED,
)
from source_control.providers.github.workflow_guard import (
    SOURCE_MUTATION_TOOLS as SOURCE_MUTATION_TOOLS,
)
from source_control.providers.github.workflow_guard import (
    GitHubLocalFirstMiddleware as _SharedGitHubLocalFirstMiddleware,
)

LOCAL_FIRST_GUIDANCE = (
    "Koba GitHub workflow: for substantial source changes, prefer one local-first cycle: "
    "checkout/clone into the persistent Terminal workspace, edit and test locally, create local "
    "commits as needed, then publish once with an authenticated Git push or one batched atomic "
    "GitHub commit. Push to the requested branch if GitHub permits it; create a PR only when "
    "repository rules require one or the user requests one. Avoid repeated GitHub API mutations; "
    "they waste API quota and fragment history."
)


class GitHubLocalFirstMiddleware(_SharedGitHubLocalFirstMiddleware):
    guidance = LOCAL_FIRST_GUIDANCE
