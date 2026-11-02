"""An operation cannot outlive or substitute its original human operator."""

from datetime import UTC, datetime

from control_panel_api.domain.panel_protocol import PanelContext


def operator_continues(original: PanelContext, fresh: PanelContext, deadline: datetime) -> bool:
    return (
        fresh.proof.user_uuid == original.proof.user_uuid
        and fresh.session.subject == original.session.subject
        and fresh.session.issuer == original.session.issuer
        and fresh.proof.role == "operator"
        and min(deadline, fresh.proof.expires_at, fresh.session.expires_at) > datetime.now(UTC)
    )


def node_mutates(action: str, module_action: str | None) -> bool:
    return action not in {"list", "setup", "runtime_policy_get"} and not (
        action == "modules" and module_action in {"catalog", "placements", "workspaces"}
    )
