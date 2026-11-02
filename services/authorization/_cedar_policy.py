"""Cedar decision adapter over facts already verified by the Authorization owner.

This module does NOT authenticate OAuth tokens or load grants from clients.
The caller must obtain grant/version/session facts from trusted owner storage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from cedarpy import PolicySet, is_authorized

from authorization.domain.current_grants import CedarOperation as CedarOperation
from authorization.domain.current_grants import CurrentGrant as CurrentGrant


class CedarPolicyError(Exception):
    """The Authorization owner cannot initialize its trusted policy set."""


class CedarPolicyEvaluator:
    """Keep a compiled Cedar policy and fail closed on stale grants/errors."""

    def __init__(self, policy_text: str) -> None:
        if not policy_text.strip():
            raise CedarPolicyError("Authorization Cedar policy is empty")
        try:
            self._policy_set = PolicySet.from_str(policy_text)
        except (TypeError, ValueError) as exc:
            raise CedarPolicyError("Authorization Cedar policy cannot be parsed") from exc

    def permits(
        self,
        operation: CedarOperation,
        grant: CurrentGrant,
        *,
        trusted_entities: Sequence[Mapping[str, object]] = (),
        now: datetime | None = None,
    ) -> bool:
        instant = datetime.now(UTC) if now is None else now
        if not grant.matches(operation, instant):
            return False

        # JSON quoting prevents identifiers or tool names from being injected
        # into the Cedar entity syntax. Owner APIs must verify principal,
        # audience, active session, current grant version and entity graph.
        request = {
            "principal": f"User::{json.dumps(str(operation.actor_uuid))}",
            "action": f"Action::{json.dumps(operation.action)}",
            "resource": (f"{operation.resource_type}::{json.dumps(str(operation.resource_uuid))}"),
            "context": {
                "project": str(operation.project_uuid),
                "agentSession": str(operation.agent_session_uuid),
                "grantVersion": grant.version,
                "isElevated": grant.is_elevated,
            },
        }
        # This is a policy layer, not a grant source. Invalid policy, missing
        # entities, or library errors can never turn a denial into an Allow.
        try:
            return (
                is_authorized(
                    request, self._policy_set, [dict(entity) for entity in trusted_entities]
                ).allowed
                is True
            )
        except Exception:  # Any engine/entity failure is an authorization denial.
            return False
