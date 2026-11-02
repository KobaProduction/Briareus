"""Derive process identity only from independently verified Node evidence."""

from hand_runtime.process_lease_domain import LeaseIdentity
from node_protocol.effect import EffectPermit, HumanEffectPermit
from terminal_hand.domain.effect_decision import OperationPrincipal
from terminal_hand.domain.human_principal import HumanOperationPrincipal

type ExecutionPrincipal = OperationPrincipal | HumanOperationPrincipal


def node_identity(permit: EffectPermit) -> LeaseIdentity:
    if isinstance(permit, HumanEffectPermit):
        return ("human", str(permit.actor_uuid), str(permit.project_uuid), permit.resource_revision)
    return (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)


def node_principal(permit: EffectPermit) -> ExecutionPrincipal:
    if isinstance(permit, HumanEffectPermit):
        return HumanOperationPrincipal(permit.actor_uuid, permit.project_uuid, permit.request_uuid)
    return OperationPrincipal(permit.actor_uuid, permit.agent_session_uuid, permit.request_uuid)
