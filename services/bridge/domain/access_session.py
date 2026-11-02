"""Legacy surface access classification and stable denial messages."""

_SAFE_ACCOUNT_DISCOVERY: dict[str, frozenset[str]] = {
    "github": frozenset({"github_accounts"}),
    "gitlab": frozenset({"accounts"}),
    "observability": frozenset({"observability_sources"}),
}
_SAFE_BRIDGE_TOOLS = frozenset(
    {
        "bridge_ping",
        "bridge_build_info",
        "bridge_backends",
        "bridge_tools",
        "bridge_capabilities",
    }
)
_MESSAGES = {
    "session_required": (
        "A session is required. Call access_session_open and retry with session_id."
    ),
    "session_invalid": "The session is invalid for this OAuth connection or MCP surface.",
    "session_expired": "The session expired. Call access_session_reissue.",
    "session_revoked": "The session was revoked. Call access_session_reissue.",
    "full_access_required": (
        "This action requires full access. Call access_session_request_full_access "
        "and ask the user to approve it in the administration UI."
    ),
    "account_scope_denied": "This session does not have full access to the requested account.",
    "rate_limited": "Too many invalid session attempts. Retry after the backoff period.",
    "oauth_session_revoked": "OAuth authorization was revoked; reconnect this MCP surface.",
}


def is_base_read_only(surface: str, tool_name: str, *, read_only_hint: bool) -> bool:
    if surface == "root" and tool_name in _SAFE_BRIDGE_TOOLS:
        return True
    if tool_name in _SAFE_ACCOUNT_DISCOVERY.get(surface, frozenset()):
        return True
    return read_only_hint


def denial_message(code: str) -> str:
    return _MESSAGES.get(code, "Access denied.")
