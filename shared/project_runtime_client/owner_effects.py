"""Signed owner-local command/outcome port for Catalog, Files, Runtime, Reverse.

Four independent databases/roles/transaction journals. No global SQL UoW,
no direct ORM imports, no cross-DB FK or event-as-authorization. Backend A11
must independently accept exact wire DTOs before binding a real transport;
without an installed trusted source every operation denies, never migrates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel

from owner_protocol.domain.authority import OwnerAuthorityUnavailable
from owner_protocol.phase_bindings import require_exact_owner_operation

from .a11_owner_wire import (
    A11OwnerCommandDTO,
    A11TargetOwner,
    VerifiedA11RevisionPort,
)
from .authorization import (
    ProjectAccessDenied,
    ProjectAction,
    ProjectInvocation,
    ProjectPermit,
    ProjectRuntimeAuthority,
)
from .domain.effect_admission import EffectAdmission
from .domain.effect_identity import OriginalEffectIdentity
from .domain.effect_protocol import (
    _A11_TARGET,
    _DB,
    EffectOwner,
    EffectPhase,
)
from .domain.effect_receipt import OwnerEffectUnavailable as OwnerEffectUnavailable
from .domain.effect_receipt import ReceiptExpectation
from .domain.identifiers import valid_uuid
from .domain.source_proof import SourceProofMismatch
from .infrastructure.effect_contracts import (
    OwnerEffectCommand as OwnerEffectCommand,
)
from .infrastructure.effect_contracts import (
    OwnerEffectReceipt as OwnerEffectReceipt,
)
from .infrastructure.effect_contracts import (
    OwnerFenceDTO as OwnerFenceDTO,
)
from .infrastructure.effect_contracts import (
    SignedOwnerEffectReceipt as SignedOwnerEffectReceipt,
)
from .infrastructure.effect_dispatch import EffectDispatch, dispatch_effect
from .infrastructure.effect_receipt import command_binding, receipt_observation, verify_attestation
from .infrastructure.owner_payloads import OwnerBusinessPayload
from .infrastructure.payload_identity import payload_effect_identity
from .infrastructure.source_proof import (
    dispatch_requirement,
    source_proof,
    status_requirement,
)
from .owner_authorization import VerifiedOwnerRecipient
from .owner_wire import (
    A11OwnerWireNotAccepted,
    OwnerWireEncoder,
    _default_a11_owner_wire,
    require_accepted_owner_lifecycle,
)


def _digest(canonical_json: str) -> str:
    serialized = canonical_json.encode("utf-8")
    if len(serialized) > 600000:
        raise ProjectAccessDenied("OWNER_EFFECT_PAYLOAD_TOO_LARGE")
    return hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True, slots=True)
class OwnerEffectReply[T: BaseModel]:
    attestation: SignedOwnerEffectReceipt
    payload: T


class OwnerEffectBackendPort(Protocol):
    """Real independent owner-local SQL dedupe+audit+outbox command.

    A11 MUST verify actual TLS/Unix recipient, caller+service, fresh Identity
    activity/revoke epoch, Control Project owner/Team member version and Access
    Session grant/revocation INSIDE the local committed owner transaction,
    then sign receipt with its own pinned key. No global Authorization UoW.
    """

    async def effect[T: BaseModel](
        self,
        invocation: ProjectInvocation,
        *,
        command: OwnerEffectCommand,
        a11_command: A11OwnerCommandDTO,
        business_payload: OwnerBusinessPayload,
        payload: BaseModel,
        expected_type: type[T],
        recipient: VerifiedOwnerRecipient,
    ) -> OwnerEffectReply[T]: ...


class OwnerEffectTrustPort(Protocol):
    """Verify the peer from this request's independently authenticated transport.

    Bind the TLS/Unix peer to the supplied operation scope; reject missing,
    expired or mismatched authentication. Invocation IDs cannot prove identity.
    """

    async def verified_recipient(self, invocation: ProjectInvocation) -> VerifiedOwnerRecipient: ...

    async def pinned_effect_owner_key(
        self,
        owner: A11TargetOwner,
        *,
        recipient: VerifiedOwnerRecipient,
    ) -> Ed25519PublicKey: ...


class OwnerEffectRecipientPort(Protocol):
    timeout_seconds: float

    async def _recipient(self, invocation: ProjectInvocation) -> VerifiedOwnerRecipient: ...


class OwnerEffectClient[PayloadT: BaseModel]:
    """One signed owner command; UNKNOWN never authorizes blind replay."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        wire_encoder: OwnerWireEncoder[PayloadT],
        backend: OwnerEffectBackendPort | None = None,
        trust: OwnerEffectTrustPort | None = None,
        a11_revisions: VerifiedA11RevisionPort | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("owner effect timeout invalid")
        self.authority = authority
        self.backend = backend
        self.trust = trust
        self.a11_revisions = a11_revisions
        self.timeout_seconds = timeout_seconds
        self._wire_encoder = wire_encoder

    def require_ready(self) -> None:
        if self.backend is None or self.trust is None or self.a11_revisions is None:
            raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")

    def require_effect_lifecycle(self, owner: EffectOwner) -> None:
        self.require_ready()
        try:
            require_accepted_owner_lifecycle(owner)
        except A11OwnerWireNotAccepted as exc:
            raise OwnerEffectUnavailable(exc.code) from exc

    async def _recipient(self, invocation: ProjectInvocation) -> VerifiedOwnerRecipient:
        self.require_ready()
        trust = self.trust
        if trust is None:
            raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                peer = await trust.verified_recipient(invocation)
        except Exception as exc:
            raise OwnerEffectUnavailable("OWNER_C2_RECIPIENT_UNAVAILABLE") from exc
        if not isinstance(peer, VerifiedOwnerRecipient):
            raise OwnerEffectUnavailable("OWNER_C2_RECIPIENT_INVALID")
        if (
            not valid_uuid(peer.service_id, version=4)
            or not valid_uuid(peer.instance_uuid, version=4)
            or peer.expires_at.tzinfo is None
            or peer.expires_at <= datetime.now(UTC)
            or peer.transport not in {"mtls", "unix-peer"}
        ):
            raise OwnerEffectUnavailable("OWNER_C2_RECIPIENT_INVALID")
        return peer

    async def execute[T: BaseModel](
        self,
        invocation: ProjectInvocation,
        *,
        owner: EffectOwner,
        phase: EffectPhase,
        action: ProjectAction,
        target_sha256: str,
        payload: PayloadT,
        expected: type[T],
        expected_version: int = 0,
        original_operation_uuid: UUID | None = None,
        expected_service_id: UUID | None = None,
        expected_instance_uuid: UUID | None = None,
    ) -> OwnerEffectReply[T]:
        """Return only after verifying pinned Ed25519 owner+original UUID.

        Inspect/reconcile require SAME original operation identity with fresh
        JWT JTIs. Transport/ACK unknown is not a failure that can be retried
        with a new idempotency UUID or released after dispatch.
        """
        # Guard the low-level port itself: callers must not bypass full owner
        # lifecycle acceptance by skipping their domain-specific facade.
        self.require_effect_lifecycle(owner)
        if not isinstance(payload, BaseModel):
            raise OwnerEffectUnavailable("OWNER_COMMAND_INVALID")
        scope = EffectAdmission(
            owner, phase, action, target_sha256, expected_version
        ).require_scope(
            invocation,
        )
        identity = OriginalEffectIdentity.bind(scope.request_uuid, original_operation_uuid)
        identity.require_payload(payload_effect_identity(payload))
        uuid = identity.operation_uuid
        permit = await self.authority.require(invocation, action)
        fence = OwnerFenceDTO.from_permit(permit)
        peer = await self._recipient(invocation)
        if (expected_service_id is not None and peer.service_id != expected_service_id) or (
            expected_instance_uuid is not None and peer.instance_uuid != expected_instance_uuid
        ):
            raise OwnerEffectUnavailable("OWNER_EFFECT_SERVICE_PEER_IDENTITY_MISMATCH")
        # A11 owner methods verify an exact operation name AND exact
        # business-only JSON schema. `payload.model_dump()` of a historical
        # A6 typed DTO does NOT match their owner-local business parameters.
        # Unsupported/OS-proof-dependent operations deny BEFORE any backend
        # command, never guess a generic `f"{owner}.{phase}"` API.
        try:
            wire = self._wire_encoder(owner, phase, payload, peer=peer)
        except A11OwnerWireNotAccepted as exc:
            raise OwnerEffectUnavailable(exc.code) from exc
        # Backend's accepted exact operation table is the authority, not a
        # larger Runtime-private phase enum or a concurrently edited A13 tree.
        try:
            require_exact_owner_operation(
                owner=owner,
                phase=phase,
                payload_type=type(payload).__name__,
                operation=wire.operation,
            )
        except OwnerAuthorityUnavailable as exc:
            raise OwnerEffectUnavailable("OWNER_BACKEND_PHASE_NOT_ACCEPTED") from exc
        a11_payload_hash = _digest(
            json.dumps(
                wire.business_payload.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        )
        version_source = self.a11_revisions
        if version_source is None:
            raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")
        try:
            async with asyncio.timeout(min(self.timeout_seconds, 5.0)):
                versions = await version_source.current_owner_revisions(
                    invocation,
                    owner=_A11_TARGET[owner],
                    action=action,
                    phase=phase,
                    operation=wire.operation,
                    payload_sha256=a11_payload_hash,
                    idempotency_key=str(uuid),
                    recipient=peer,
                    permit=permit,
                )
        except Exception as exc:
            raise OwnerEffectUnavailable("OWNER_A11_CURRENT_PROOF_UNAVAILABLE") from exc
        try:
            source_proof(versions).require_for(
                dispatch_requirement(
                    owner=_A11_TARGET[owner],
                    operation=wire.operation,
                    operation_uuid=uuid,
                    payload_sha256=a11_payload_hash,
                    permit=permit,
                    peer=peer,
                )
            )
        except SourceProofMismatch as exc:
            raise OwnerEffectUnavailable("OWNER_A11_AUTHORITY_REVISION_MISMATCH") from exc
        a11_command = A11OwnerCommandDTO(
            operation_uuid=uuid,
            caller_user_id=permit.actor_id,
            project_id=permit.project_id,
            session_uuid=permit.session_uuid,
            target_owner=_A11_TARGET[owner],
            operation=wire.operation,
            idempotency_key=str(uuid),
            payload_sha256=a11_payload_hash,
            expected_identity_revision=versions.expected_identity_revision,
            expected_control_revision=versions.expected_control_revision,
            expected_control_resource_revision=versions.expected_control_resource_revision,
            expected_team_id=versions.expected_team_id,
            expected_team_revision=versions.expected_team_revision,
            expected_team_resource_revision=versions.expected_team_resource_revision,
            expected_access_revision=versions.expected_access_revision,
        )
        if permit.expires_at <= datetime.now(UTC) or peer.expires_at <= datetime.now(UTC):
            raise OwnerEffectUnavailable("OWNER_ORIGINAL_GRANT_EXPIRED_BEFORE_DISPATCH")
        payload_hash = _digest(
            json.dumps(
                {
                    "owner": owner,
                    "phase": phase,
                    "command": type(payload).__name__,
                    "body": payload.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        )
        command = OwnerEffectCommand(
            owner=owner,
            owner_database=_DB[owner],
            phase=phase,
            action=action,
            operation_uuid=uuid,
            idempotency_uuid=uuid,
            project_id=permit.project_id,
            agent_session_uuid=permit.session_uuid,
            actor_id=permit.actor_id,
            recipient_service_id=peer.service_id,
            recipient_instance_uuid=peer.instance_uuid,
            request_sha256=scope.fingerprint,
            target_sha256=target_sha256,
            payload_sha256=payload_hash,
            payload_type=type(payload).__name__,
            expected_version=expected_version,
            fence=fence,
        )
        response = await dispatch_effect(
            self.backend,
            invocation,
            dispatch=EffectDispatch(command, a11_command, wire, payload, expected, peer),
            timeout_seconds=self.timeout_seconds,
        )
        return await self._accept_response(
            invocation,
            response=response,
            expected=expected,
            command=command,
            permit=permit,
            peer=peer,
        )

    async def _accept_response[T: BaseModel](
        self,
        invocation: ProjectInvocation,
        *,
        response: OwnerEffectReply[T],
        expected: type[T],
        command: OwnerEffectCommand,
        permit: ProjectPermit,
        peer: VerifiedOwnerRecipient,
    ) -> OwnerEffectReply[T]:
        trust = self.trust
        if trust is None:
            raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                public_key = await trust.pinned_effect_owner_key(
                    _A11_TARGET[command.owner],
                    recipient=peer,
                )
            if not isinstance(public_key, Ed25519PublicKey):
                raise OwnerEffectUnavailable("OWNER_EFFECT_PINNED_KEY_REQUIRED", unknown=True)
            if not isinstance(response, OwnerEffectReply):
                raise OwnerEffectUnavailable("OWNER_EFFECT_REPLY_TYPE_INVALID", unknown=True)
            if not isinstance(response.payload, expected):
                raise OwnerEffectUnavailable("OWNER_EFFECT_REPLY_TYPE_INVALID", unknown=True)
            attestation = verify_attestation(
                response.attestation,
                key=public_key,
                owner=_A11_TARGET[command.owner],
                recipient=peer,
            )
            receipt_observation(response.attestation.receipt).require_for(
                ReceiptExpectation(
                    binding=command_binding(command),
                    result_sha256=_digest(
                        json.dumps(
                            response.payload.model_dump(mode="json"),
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                            allow_nan=False,
                        )
                    ),
                    minimum_revision=command.expected_version,
                    recipient_expires_at=peer.expires_at,
                    token_expires_at=attestation.expires_at,
                    now=datetime.now(UTC),
                )
            )
            fresh = await self.authority.require(invocation, command.action)
            if (
                fresh.owner_fence != permit.owner_fence
                or fresh.project_id != permit.project_id
                or fresh.actor_id != permit.actor_id
                or fresh.session_uuid != permit.session_uuid
                or fresh.project_owner_scope != permit.project_owner_scope
                or fresh.project_owner_id != permit.project_owner_id
            ):
                raise OwnerEffectUnavailable("OWNER_EFFECT_ACCESS_CHANGED_AFTER_ACK", unknown=True)
            return response
        except OwnerEffectUnavailable:
            raise
        except Exception as exc:
            raise OwnerEffectUnavailable("OWNER_EFFECT_ATTESTATION_UNKNOWN", unknown=True) from exc

    async def verify_signed_status_v2(
        self,
        invocation: ProjectInvocation,
        *,
        command: OwnerEffectCommand,
        source_command: A11OwnerCommandDTO,
        signed: object,
    ) -> Literal["UNKNOWN", "COMMITTED", "DENIED"]:
        """Check owner-signed A12 status for ORIGINAL UUID, never replay.

        Signature, signer, recipient, original key SHA, exact command fields,
        owner revision, UTC TTL and *fresh* Identity/Control/Access are all
        checked. A signed COMMITTED owner-row state is not an OS completion
        receipt; the native Files/Ghidra/Terminal source must STILL supply
        independently verified evidence before any irreversible completion.
        """
        from .owner_status import SignedOwnerEffectStatusV2, verify_signed_owner_status_v2

        if not isinstance(signed, SignedOwnerEffectStatusV2):
            raise OwnerEffectUnavailable("A12_OWNER_SIGNED_STATUS_REQUIRED", unknown=True)
        if not isinstance(command, OwnerEffectCommand):
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_ORIGINAL_SCOPE_MISMATCH", unknown=True)
        if not isinstance(source_command, A11OwnerCommandDTO):
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_ORIGINAL_SCOPE_MISMATCH", unknown=True)
        if (
            command.operation_uuid != source_command.operation_uuid
            or source_command.idempotency_key != str(command.operation_uuid)
            or invocation.operation_scope is None
            or invocation.operation_scope.action != command.action
            or invocation.operation_scope.project_id != invocation.project_id
            or invocation.operation_scope.agent_session_uuid != invocation.session_uuid
            or command.project_id != invocation.project_id
            or command.agent_session_uuid != invocation.session_uuid
        ):
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_ORIGINAL_SCOPE_MISMATCH", unknown=True)
        self.require_ready()
        # Signed inspection cannot validate an operation/phase combination
        # the producer has not accepted, even if the JWS fields look valid.
        try:
            require_exact_owner_operation(
                owner=command.owner,
                phase=command.phase,
                payload_type=command.payload_type,
                operation=source_command.operation,
            )
        except OwnerAuthorityUnavailable as exc:
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_PHASE_UNACCEPTED", unknown=True) from exc
        permit = await self._status_permit(invocation, command)
        peer = await self._recipient(invocation)
        if (
            peer.service_id != command.recipient_service_id
            or peer.instance_uuid != command.recipient_instance_uuid
        ):
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_RECIPIENT_CHANGED", unknown=True)
        trust = self.trust
        if trust is None:
            raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                pinned = await trust.pinned_effect_owner_key(
                    _A11_TARGET[command.owner],
                    recipient=peer,
                )
        except Exception as exc:
            raise OwnerEffectUnavailable(
                "A12_OWNER_STATUS_PINNED_KEY_UNAVAILABLE", unknown=True
            ) from exc
        # v2 status is not a bearer and cannot reuse a stale source-command
        # projection. Repeat the *real* A11 triple-owner verification before
        # consuming a current owner-local SQL status signature.
        revision_source = self.a11_revisions
        if revision_source is None:
            raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")
        try:
            async with asyncio.timeout(min(self.timeout_seconds, 5.0)):
                versions = await revision_source.current_owner_revisions(
                    invocation,
                    owner=_A11_TARGET[command.owner],
                    action=command.action,
                    phase=command.phase,
                    operation=source_command.operation,
                    payload_sha256=source_command.payload_sha256,
                    idempotency_key=source_command.idempotency_key,
                    recipient=peer,
                    permit=permit,
                )
        except Exception as exc:
            raise OwnerEffectUnavailable(
                "A12_OWNER_STATUS_CURRENT_SOURCE_UNAVAILABLE", unknown=True
            ) from exc
        try:
            source_proof(versions).require_for(
                status_requirement(
                    command=source_command,
                    actor_uuid=command.actor_id,
                    project_uuid=command.project_id,
                    session_uuid=command.agent_session_uuid,
                    operation_uuid=command.operation_uuid,
                    permit=permit,
                    peer=peer,
                )
            )
        except SourceProofMismatch as exc:
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_SOURCE_REVOKED", unknown=True) from exc
        status = verify_signed_owner_status_v2(
            signed,
            pinned_key=pinned,
            command=command,
            source_command=source_command,
            recipient=peer,
        )
        refreshed = await self.authority.require(invocation, command.action)
        if (
            OwnerFenceDTO.from_permit(refreshed) != command.fence
            or refreshed.actor_id != command.actor_id
            or refreshed.project_id != command.project_id
            or refreshed.session_uuid != command.agent_session_uuid
            or refreshed.project_owner_scope != permit.project_owner_scope
            or refreshed.project_owner_id != permit.project_owner_id
            or refreshed.project_access_revision != permit.project_access_revision
            or refreshed.expires_at <= datetime.now(UTC)
            or status.expires_at <= datetime.now(UTC)
        ):
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_REVOKED_AFTER_VERIFY", unknown=True)
        return status.state

    async def _status_permit(
        self,
        invocation: ProjectInvocation,
        command: OwnerEffectCommand,
    ) -> ProjectPermit:
        """Reacquire current authority for the original inspected operation."""
        permit = await self.authority.require(invocation, command.action)
        scope = invocation.operation_scope
        if scope is None:
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_REVOCATION_FENCE_CHANGED", unknown=True)
        if (
            permit.project_id != command.project_id
            or permit.session_uuid != command.agent_session_uuid
            or permit.actor_id != command.actor_id
            or OwnerFenceDTO.from_permit(permit) != command.fence
            or scope.request_uuid != command.operation_uuid
            or scope.fingerprint != command.request_sha256
        ):
            raise OwnerEffectUnavailable("A12_OWNER_STATUS_REVOCATION_FENCE_CHANGED", unknown=True)
        return permit


class _CompatibilityOwnerEffectClient[PayloadT: BaseModel](OwnerEffectClient[PayloadT]):
    """The compatibility roots bind the same nominal shared payload identities."""

    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        *,
        backend: OwnerEffectBackendPort | None = None,
        trust: OwnerEffectTrustPort | None = None,
        a11_revisions: VerifiedA11RevisionPort | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        super().__init__(
            authority,
            backend=backend,
            trust=trust,
            a11_revisions=a11_revisions,
            timeout_seconds=timeout_seconds,
            wire_encoder=_default_a11_owner_wire,
        )
