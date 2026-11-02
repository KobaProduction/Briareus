"""Distinct human project contexts and unchanged agent profile identities."""

import hashlib
import json

from node_protocol.effect import EffectPermit, HumanEffectPermit
from web_hand.domain.profile import LeaseIdentity


def require_browser_input_authority(permit: EffectPermit, tool: str) -> None:
    if tool == "local_browser_input" and not isinstance(permit, HumanEffectPermit):
        raise ValueError("Human browser input requires signed project-user authority")


def execution_identity(permit: EffectPermit) -> LeaseIdentity:
    if isinstance(permit, HumanEffectPermit):
        return (
            "human",
            str(permit.actor_uuid),
            str(permit.project_uuid),
            permit.resource_revision,
        )
    return (
        str(permit.actor_uuid),
        str(permit.agent_session_uuid),
        permit.grant_revision,
    )


def profile_key(permit: EffectPermit) -> str:
    context = (
        ("human", str(permit.actor_uuid), str(permit.project_uuid))
        if isinstance(permit, HumanEffectPermit)
        else (str(permit.actor_uuid), str(permit.agent_session_uuid))
    )
    return hashlib.sha256(
        json.dumps(
            context, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()
