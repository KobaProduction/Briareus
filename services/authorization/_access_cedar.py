"""Access-owned Cedar policy for current Project AgentSession grants.

Cedar decides based on a freshly loaded Authorization row, never a caller
assertion. The initial policy is code-owned and deliberately conservative.
Future MCP policy management may replace the policy set only through an
authenticated, versioned owner API, not ENV/client-provided Cedar text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from authorization._cedar_policy import CedarOperation, CedarPolicyEvaluator, CurrentGrant
from authorization._resource_scope import (
    EffectResource,
    HandName,
    resource_key,
    stored_grant_matches,
)
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.domain.current_grants import ProjectGrantState

# Two explicit policy tiers; elevated rights can never be authorized by a
# normal AgentSession even if malformed/stale DB JSON lists those grants.
_BASELINE_POLICY = """
// Admission is only a connection-level check. The Hand separately evaluates
// the specific tool operation before every protected effect.
permit(principal is User, action == Action::"mcp.connect", resource is Project)
when { context.grantVersion >= 1 };

permit(principal is User,
       action in [Action::"files.read", Action::"project.metadata.read"],
       resource is Project)
when { context.grantVersion >= 1 };

// A Hand effect additionally requires an exact durable resource-scoped grant
// verified against its tool arguments and a trusted authenticated Hand peer.
permit(principal is User,
       action in [Action::"files.read", Action::"project.metadata.read"],
       resource is HandResource)
when { context.grantVersion >= 1 };

permit(principal is User,
       action in [Action::"files.write", Action::"terminal.execute",
                  Action::"web.access", Action::"analysis.import",
                  Action::"agents.manage", Action::"integrations.use",
                  Action::"variables.use", Action::"integrations.manage",
                  Action::"variables.manage"],
       resource is Project)
when { context.grantVersion >= 1 && context.isElevated == true };

permit(principal is User,
       action in [Action::"files.write", Action::"terminal.execute",
                  Action::"web.access", Action::"analysis.import",
                  Action::"agents.manage", Action::"integrations.use",
                  Action::"variables.use", Action::"integrations.manage",
                  Action::"variables.manage"],
       resource is HandResource)
when { context.grantVersion >= 1 && context.isElevated == true };
"""

_POLICY = CedarPolicyEvaluator(_BASELINE_POLICY)


def _operation_names(operations: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if (
        operations is None
        or not 1 <= len(operations) <= 32
        or any(len(value) > 128 for value in operations)
    ):
        return None
    return tuple(operations)


def permits_current_project_grant(
    *,
    row: ProjectAgentSessionRow,
    actor_uuid: UUID,
    project_uuid: UUID,
    operation: str,
    expected_version: int,
    hand: HandName | None = None,
    tool: str | None = None,
    resource: EffectResource | None = None,
) -> bool:
    """Deny absent, stale, revoked or actor-mismatched durable grants."""
    state = ProjectGrantState(
        row.session_uuid,
        row.created_by_principal_id,
        row.project_id,
        row.status,
        row.revoked_at,
        row.version,
        _operation_names(row.grants.operations),
    )
    if not state.permits(
        actor_uuid=actor_uuid,
        project_uuid=project_uuid,
        operation=operation,
        expected_version=expected_version,
    ):
        return False
    scoped = hand is not None or tool is not None or resource is not None
    if scoped and (
        hand is None
        or tool is None
        or resource is None
        or operation == "mcp.connect"
        or not stored_grant_matches(
            stored=row.grants.resources,
            hand=hand,
            tool=tool,
            action=operation,
            resource=resource,
            project_uuid=project_uuid,
        )
    ):
        return False
    # Unscoped calls are permitted only for the original verified internal
    # owner operation API and Gateway mcp.connect. The private /decide Hand
    # route REQUIRES a bound resource in DecisionCommand.
    target: UUID | str = project_uuid
    if scoped:
        if hand is None or tool is None or resource is None:
            return False
        target = resource_key(hand, tool, resource)
    return _POLICY.permits(
        CedarOperation(
            actor_uuid=actor_uuid,
            agent_session_uuid=row.session_uuid,
            project_uuid=project_uuid,
            action=operation,
            resource_type="HandResource" if scoped else "Project",
            resource_uuid=target,
        ),
        CurrentGrant(
            actor_uuid=row.created_by_principal_id,
            agent_session_uuid=row.session_uuid,
            project_uuid=row.project_id,
            action=operation,
            resource_uuid=target,
            active=row.status == "active" and row.revoked_at is None,
            expires_at=row.hard_expires_at,
            version=row.version,
            minimum_current_version=expected_version,
            is_elevated=row.is_elevated,
        ),
        now=datetime.now(UTC),
    )
