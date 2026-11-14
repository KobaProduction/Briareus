from __future__ import annotations

import asyncio
import logging

from briareus_json_values import JsonObject
from briareus_service_discovery import ServiceDiscovery

logger = logging.getLogger(__name__)

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


async def with_git_auth_guidance(
    result: JsonObject, *, discovery: ServiceDiscovery | None = None
) -> JsonObject:
    """Suggest only providers confirmed available by node-scoped service discovery."""
    failed = result.get("exit_code") not in {0, None} or result.get("state") == "failed"
    if not failed or result.get("timed_out"):
        return result
    output = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr", "output"))
    output = output.casefold()
    if discovery is None or not any(pattern in output for pattern in _AUTH_ERRORS):
        return result
    try:
        snapshot = await asyncio.wait_for(discovery.snapshot(), timeout=2)
    except Exception:
        logger.warning("Git auth guidance omitted: service availability could not be verified")
        return result
    available = {service.id for service in snapshot.services if service.connected}
    providers: JsonObject = {}
    if "github" in available:
        providers["github"] = {
            "accounts_tool": "github_accounts",
            "authorize_tool": "github_authorize_local_git",
            "required_arguments": ["account_id", "repository", "destination"],
        }
    if "gitlab" in available:
        providers["gitlab"] = {
            "accounts_tool": "accounts",
            "authorize_tool": "authorize_local_git",
            "required_arguments": ["account_id", "project", "destination"],
        }
    if not providers:
        return result
    return {
        **result,
        "git_auth_hint": {
            "reason": "git_authentication_failed",
            "message": (
                "The MCP providers listed below are available on this node. Before asking "
                "the user for credentials, check the matching provider account and local Git "
                "authorization tool. Service availability does not establish account permissions "
                "or that the provider's tool is connected in the calling client's session. "
                "For already-authorized repository work, authorize the existing checkout and "
                "retry the failed command. Respect account identity and publication restrictions; "
                "do not switch accounts, copy tokens into chat, or bypass disabled "
                "transport policy."
            ),
            **providers,
            "destination": (
                "Local Git destination MUST be relative to SERVER_MOUNT_PATH: "
                "destination='projects/ai-science/repo', NEVER "
                "destination='/workspace/projects/ai-science/repo'. "
                "Terminal cwd/git -C may be absolute; those are DIFFERENT parameters. "
                "Prefer the exact 'path' output from checkout_repository(mode='git'). "
                "For an existing checkout, identify its root with "
                "git -C <working-directory> rev-parse --show-toplevel and remove "
                "the SERVER_MOUNT_PATH prefix. Check the correct account and remote; "
                "do not create a new checkout just to repair authorization."
            ),
            "if_authorization_fails": (
                "Report the specific MCP account, policy or permission failure. Do not infer "
                "separate filesystems from an empty credential file."
            ),
        },
    }
