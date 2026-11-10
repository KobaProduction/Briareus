from __future__ import annotations

from briareus_json_values import JsonObject

_AUTH_ERRORS = (
    "fatal: authentication failed",
    "fatal: could not read username",
    "fatal: could not read password",
    "fatal: authentication required",
    "http basic: access denied",
    "permission denied (publickey)",
    "password authentication was removed",
    "invalid username or token",
    "terminal prompts disabled",
)


def with_git_auth_guidance(result: JsonObject) -> JsonObject:
    """Point failed Git authentication to provider MCP tools without copying output or secrets."""
    failed = result.get("exit_code") not in {0, None} or result.get("state") == "failed"
    if not failed or result.get("timed_out"):
        return result
    output = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr", "output"))
    output = output.casefold()
    if not any(pattern in output for pattern in _AUTH_ERRORS):
        return result
    return {
        **result,
        "git_auth_hint": {
            "reason": "git_authentication_failed",
            "message": (
                "Terminal Git authentication failure does not establish that connected MCP "
                "repository access is unavailable. Before asking the user for credentials, "
                "check the matching GitHub/GitLab MCP account and local Git authorization tool. "
                "For already-authorized repository work, authorize the existing checkout and "
                "retry the failed command. Respect account identity and publication restrictions; "
                "do not switch accounts, copy tokens into chat, or bypass disabled "
                "transport policy."
            ),
            "github": {
                "accounts_tool": "github_accounts",
                "authorize_tool": "github_authorize_local_git",
                "required_arguments": ["account_id", "repository", "destination"],
            },
            "gitlab": {
                "accounts_tool": "accounts",
                "authorize_tool": "authorize_local_git",
                "required_arguments": ["account_id", "project", "destination"],
            },
            "destination": (
                "Use the actual checkout root relative to the Server mount, e.g. "
                "projects/ai-science/repo, not a laptop path or just the workspace_id. "
                "Inspect the command's actual working directory and remote, including git -C."
            ),
            "if_authorization_fails": (
                "Report the specific MCP account, policy or permission failure. Do not infer "
                "separate filesystems from an empty credential file."
            ),
        },
    }
