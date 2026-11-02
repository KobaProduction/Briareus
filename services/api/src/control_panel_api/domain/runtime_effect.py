"""Human runtime output may be released only under the original current identity."""

from datetime import UTC, datetime

from control_panel_api.domain.panel_protocol import PanelContext


def quick_terminal_command(hand: str, tool: str, seconds: int | float | None) -> bool:
    if hand != "terminal" or tool != "terminal_exec":
        return True
    if type(seconds) is int or type(seconds) is float:
        return 0 < seconds <= 3
    return False


def runtime_actor_continues(original: PanelContext, fresh: PanelContext) -> bool:
    return (
        fresh.session.subject == original.session.subject
        and fresh.session.issuer == original.session.issuer
        and fresh.proof.user_uuid == original.proof.user_uuid
        and min(
            original.session.expires_at,
            original.proof.expires_at,
            fresh.session.expires_at,
            fresh.proof.expires_at,
        )
        > datetime.now(UTC)
    )
