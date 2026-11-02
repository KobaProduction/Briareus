"""Translate verified boundary DTOs into framework-free authority facts."""

from uuid import UUID

from project_runtime_client.a11_owner_wire import A11OwnerCommandDTO, VerifiedA11SourceVersions
from project_runtime_client.authorization import ProjectOwnerFence, ProjectPermit
from project_runtime_client.domain.source_proof import (
    AuthorityEpochs,
    AuthorityVersions,
    EffectSubject,
    ResourceVersions,
    SourceProof,
    SourceProofMismatch,
    SourceProofRequirement,
)
from project_runtime_client.owner_authorization import VerifiedOwnerRecipient


def source_proof(versions: VerifiedA11SourceVersions) -> SourceProof:
    if not isinstance(versions, VerifiedA11SourceVersions):
        raise SourceProofMismatch("verified source projection required")
    return SourceProof(
        subject=EffectSubject(
            versions.owner,
            versions.audience,
            versions.operation,
            versions.idempotency_key,
            versions.payload_sha256,
            versions.recipient_service_id,
            versions.recipient_instance_uuid,
            versions.actor_user_id,
            versions.project_id,
            versions.session_uuid,
            versions.operation_uuid,
        ),
        versions=AuthorityVersions(
            versions.expected_identity_revision,
            versions.expected_control_revision,
            versions.expected_access_revision,
        ),
        epochs=AuthorityEpochs(
            versions.identity_epoch, versions.platform_epoch, versions.access_epoch
        ),
        resources=ResourceVersions(
            versions.expected_control_resource_revision,
            versions.expected_team_id,
            versions.expected_team_revision,
            versions.expected_team_resource_revision,
        ),
        expires_at=versions.expires_at,
    )


def dispatch_requirement(
    *,
    owner: str,
    operation: str,
    operation_uuid: UUID,
    payload_sha256: str,
    permit: ProjectPermit,
    peer: VerifiedOwnerRecipient,
) -> SourceProofRequirement:
    fence = permit.owner_fence
    if not isinstance(fence, ProjectOwnerFence):
        raise SourceProofMismatch("owner authority fence required")
    return SourceProofRequirement(
        subject=EffectSubject(
            owner,
            f"briareus:{owner}",
            operation,
            str(operation_uuid),
            payload_sha256,
            peer.service_id,
            peer.instance_uuid,
            permit.actor_id,
            permit.project_id,
            permit.session_uuid,
            operation_uuid,
        ),
        versions=AuthorityVersions(
            fence.identity_version,
            fence.control_state_version,
            fence.access_session_version,
        ),
        epochs=AuthorityEpochs(
            fence.identity_authority_epoch,
            fence.control_authority_epoch,
            fence.access_authority_epoch,
        ),
        owner_scope=permit.project_owner_scope,
        owner_uuid=permit.project_owner_id,
        recipient_expires_at=peer.expires_at,
        grant_expires_at=permit.expires_at,
    )


def status_requirement(
    *,
    command: A11OwnerCommandDTO,
    actor_uuid: UUID,
    project_uuid: UUID,
    session_uuid: UUID,
    operation_uuid: UUID,
    permit: ProjectPermit,
    peer: VerifiedOwnerRecipient,
) -> SourceProofRequirement:
    fence = permit.owner_fence
    if not isinstance(fence, ProjectOwnerFence):
        raise SourceProofMismatch("owner authority fence required")
    return SourceProofRequirement(
        subject=EffectSubject(
            command.target_owner,
            f"briareus:{command.target_owner}",
            command.operation,
            command.idempotency_key,
            command.payload_sha256,
            peer.service_id,
            peer.instance_uuid,
            actor_uuid,
            project_uuid,
            session_uuid,
            operation_uuid,
        ),
        versions=AuthorityVersions(
            command.expected_identity_revision,
            command.expected_control_revision,
            command.expected_access_revision,
        ),
        epochs=AuthorityEpochs(
            fence.identity_authority_epoch,
            fence.control_authority_epoch,
            fence.access_authority_epoch,
        ),
        owner_scope=permit.project_owner_scope,
        owner_uuid=permit.project_owner_id,
        recipient_expires_at=peer.expires_at,
        grant_expires_at=permit.expires_at,
        resources=ResourceVersions(
            command.expected_control_resource_revision,
            command.expected_team_id,
            command.expected_team_revision,
            command.expected_team_resource_revision,
        ),
    )
