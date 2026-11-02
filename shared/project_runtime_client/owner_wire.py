"""Accepted A11 owner source-command ABI, NOT a public RPC transport.

Only commands whose owner name, operation and business-body SHA preimage are
independently confirmed from the accepted Backend A11 owner source are mapped.
Missing owner-local APIs, signed native OS evidence, credential custody and
signed result JWS MUST DENY, not silently send a guessed generic operation.

The A11 command JSON is the canonical Pydantic `OwnerCommandDTO` metadata,
while `business_payload` serializes exactly the `require_signed_payload` fields
inside the accepted owner method. Those are DIFFERENT signed preimages from
the historical A6 `FilesSignedIntent` and the Runtime private effect envelope.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

from project_runtime_client.domain.owner_wire import (
    A11OwnerWireNotAccepted as A11OwnerWireNotAccepted,
)
from project_runtime_client.domain.owner_wire import (
    OwnerPeerBinding,
    require_catalog_query,
    require_complete_lifecycle,
    require_files_reservation,
    require_phase,
)

from .infrastructure.owner_payloads import (
    CatalogListPayload,
    FilesDispatchPayload,
    FilesReservePayload,
    FilesTransitionPayload,
    NativeDispatchPayload,
    NativeTransitionPayload,
    OwnerBusinessPayload,
    RuntimeOpenPayload,
    RuntimeRenewPayload,
    RuntimeRevokePayload,
)
from .owner_authorization import VerifiedOwnerRecipient

if TYPE_CHECKING:
    from .analysis.native_import import NativeImportTransition
    from .files.signed import FilesReserve, FilesTransition


A11EffectOwner = Literal["catalog", "files", "execution", "reverse"]

# The accepted A11 Backend SOURCE offers only these small subsets. A full
# external-effect lifecycle also needs a signed OS/native observation,
# UNKNOWN-inspect/reconcile, durable cleanup and per-owner signed result ACK.
# Do not make a Files socket/write or an Execution ACTIVE SQL lease merely
# because the RESERVE/OPEN method exists while the rest remains unaccepted.
_ACCEPTED_OWNER_PHASES: dict[A11EffectOwner, frozenset[str]] = {
    "catalog": frozenset(),
    "files": frozenset({"reserve", "dispatch"}),
    "execution": frozenset({"open", "heartbeat", "revoke"}),
    "reverse": frozenset(),
}
_REQUIRED_EFFECT_PHASES: dict[A11EffectOwner, frozenset[str]] = {
    "catalog": frozenset({"read", "reserve", "revoke", "reconcile"}),
    "files": frozenset({"reserve", "dispatch", "finalize", "inspect", "reconcile", "mark_unknown"}),
    "execution": frozenset(
        {"open", "heartbeat", "revoke", "queue_job", "start_job", "finish_job", "confirm_cleanup"}
    ),
    "reverse": frozenset({"claim", "dispatch", "inspect", "reconcile", "mark_unknown"}),
}


def require_accepted_owner_lifecycle(owner: A11EffectOwner) -> None:
    if owner not in _ACCEPTED_OWNER_PHASES:
        raise A11OwnerWireNotAccepted("A12_OWNER_COMPLETE_SIGNED_EFFECT_LIFECYCLE_REQUIRED")
    require_complete_lifecycle(_ACCEPTED_OWNER_PHASES[owner], _REQUIRED_EFFECT_PHASES[owner])


@dataclass(frozen=True, slots=True)
class A11OwnerWire:
    operation: str
    business_payload: OwnerBusinessPayload
    # The backend signs/verifies each owner-local effect again; this structure
    # does NOT authenticate an arbitrary native OS observation or SQL row.


class OwnerWireEncoder[PayloadT: BaseModel](Protocol):
    def __call__(
        self, owner: A11EffectOwner, phase: str, payload: PayloadT, *, peer: VerifiedOwnerRecipient
    ) -> A11OwnerWire: ...


@dataclass(frozen=True, slots=True)
class OwnerPayloadAdapters[PayloadT: BaseModel]:
    files: Callable[[str, PayloadT, OwnerPeerBinding], A11OwnerWire]
    reverse: Callable[[str, PayloadT, OwnerPeerBinding], A11OwnerWire]


def _peer(peer: VerifiedOwnerRecipient) -> OwnerPeerBinding:
    if not isinstance(peer, VerifiedOwnerRecipient):
        raise A11OwnerWireNotAccepted("A11_OWNER_VERIFIED_PEER_REQUIRED")
    return OwnerPeerBinding(peer.service_id, peer.instance_uuid)


def _execution_wire(phase: str, payload: BaseModel, peer: OwnerPeerBinding) -> A11OwnerWire:
    from .a6_runtime import RuntimeLeaseCommand, RuntimeOpenCommand

    if phase == "open" and isinstance(payload, RuntimeOpenCommand):
        if payload.instance_uuid != peer.instance_uuid:
            raise A11OwnerWireNotAccepted("A11_RUNTIME_OWNER_INSTANCE_MISMATCH")
        return A11OwnerWire(
            "runtime.session.open",
            RuntimeOpenPayload(
                runtime_session_uuid=payload.runtime_session_uuid,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
                kind=payload.kind,
                idle_ttl_seconds=payload.idle_seconds,
                hard_ttl_seconds=payload.hard_seconds,
            ),
        )
    if phase == "heartbeat" and isinstance(payload, RuntimeLeaseCommand):
        require_phase(payload.phase, "heartbeat", "A11_RUNTIME_HEARTBEAT_PHASE_INVALID")
        return A11OwnerWire(
            "runtime.session.renew",
            RuntimeRenewPayload(
                runtime_session_uuid=payload.runtime_session_uuid,
                expected_version=payload.expected_version,
                expected_lease_nonce=payload.lease_nonce,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
            ),
        )
    if phase == "revoke" and isinstance(payload, RuntimeLeaseCommand):
        require_phase(payload.phase, "revoke", "A11_RUNTIME_REVOKE_PHASE_INVALID")
        # The Backend local SQL revoke checks service+instance+CAS only;
        # the Runtime consumer additionally requires a VERIFIED prior
        # owner nonce/short-lived lease before constructing this command.
        return A11OwnerWire(
            "runtime.session.revoke",
            RuntimeRevokePayload(
                runtime_session_uuid=payload.runtime_session_uuid,
                expected_version=payload.expected_version,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
            ),
        )
    # Job queue/dispatch carries an OS effect and a separately accepted
    # SQL reservation/cgroup-proof protocol, not inferred from statuses.
    raise A11OwnerWireNotAccepted("A11_EXECUTION_JOB_PHASE_UNACCEPTED")


def _catalog_wire(phase: str, payload: BaseModel, _peer: OwnerPeerBinding) -> A11OwnerWire:
    from .catalog_owner import CatalogListRequest

    if phase == "read" and isinstance(payload, CatalogListRequest):
        require_catalog_query(payload.limit, payload.scope)
        name = "integrations" if payload.kind == "integration" else "variables"
        return A11OwnerWire(
            f"catalog.{name}.list",
            CatalogListPayload(kind=name, scope=payload.scope, alias_key=None, limit=payload.limit),
        )
    # Generic provider.read is NOT Catalog credential.reserve/redeem and
    # must not substitute for a one-use scoped secret custodian.
    raise A11OwnerWireNotAccepted("A11_CATALOG_ONE_USE_OPERATION_UNACCEPTED")


def _encode_files_wire(
    phase: str,
    payload: BaseModel,
    peer: OwnerPeerBinding,
    *,
    reserve_type: type[FilesReserve],
    transition_type: type[FilesTransition],
    fingerprint: Callable[[str], str],
) -> A11OwnerWire:
    if phase == "reserve" and isinstance(payload, reserve_type):
        require_files_reservation(payload.expected_file_version, payload.maximum_bytes)
        return A11OwnerWire(
            "files.write.reserve",
            FilesReservePayload(
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
                path_digest=fingerprint(payload.destination),
                content_sha256=payload.expected_sha256,
                planned_bytes=payload.maximum_bytes,
                expected_file_version=payload.expected_file_version,
                ttl_seconds=600,
            ),
        )
    if phase == "dispatch" and isinstance(payload, transition_type):
        require_phase(payload.phase, "dispatch", "A11_FILES_DISPATCH_PHASE_MISMATCH")
        return A11OwnerWire(
            "files.write.dispatch",
            FilesDispatchPayload(
                reservation_id=payload.reservation_id,
                reservation_operation_uuid=payload.operation_uuid,
                expected_reservation_version=payload.expected_version,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
            ),
        )
    # A13 candidate SOURCE preimages remain denied by the lifecycle gates.
    if phase in {"release", "mark_unknown"} and isinstance(payload, transition_type):
        required = "release" if phase == "release" else "unknown"
        require_phase(payload.phase, required, "A13_FILES_TRANSITION_PHASE_MISMATCH")
        return A11OwnerWire(
            f"files.write.{phase}",
            FilesTransitionPayload(
                reservation_id=payload.reservation_id,
                original_operation_uuid=payload.operation_uuid,
                expected_version=payload.expected_version,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
            ),
        )
    # Reconcile still needs independently verified native evidence.
    raise A11OwnerWireNotAccepted("A11_FILES_OWNER_PHASE_UNACCEPTED")


def _encode_reverse_wire(
    phase: str,
    payload: BaseModel,
    peer: OwnerPeerBinding,
    *,
    transition_type: type[NativeImportTransition],
) -> A11OwnerWire:
    if phase == "dispatch" and isinstance(payload, transition_type):
        require_phase(payload.phase, "dispatch", "A11_NATIVE_DISPATCH_PHASE_INVALID")
        return A11OwnerWire(
            "reverse.import.dispatch",
            NativeDispatchPayload(
                import_uuid=payload.import_uuid,
                original_operation_uuid=payload.operation_uuid,
                expected_import_version=payload.expected_version,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
            ),
        )
    # A13 candidate only: cancel precedes dispatch; UNKNOWN keeps ORIGINAL UUID.
    if phase in {"cancel", "mark_unknown"} and isinstance(payload, transition_type):
        required = "cancel" if phase == "cancel" else "unknown"
        require_phase(payload.phase, required, "A13_NATIVE_TRANSITION_PHASE_MISMATCH")
        return A11OwnerWire(
            f"reverse.import.{phase}",
            NativeTransitionPayload(
                import_uuid=payload.import_uuid,
                original_operation_uuid=payload.operation_uuid,
                expected_version=payload.expected_version,
                service_id=peer.service_id,
                instance_uuid=peer.instance_uuid,
            ),
        )
    # Claim and reconcile still require independently authenticated native proof.
    raise A11OwnerWireNotAccepted("A11_REVERSE_NATIVE_PROOF_UNACCEPTED")


def _files_wire(phase: str, payload: BaseModel, peer: OwnerPeerBinding) -> A11OwnerWire:
    from .files.signed import FilesReserve, FilesTransition, path_fingerprint

    return _encode_files_wire(
        phase,
        payload,
        peer,
        reserve_type=FilesReserve,
        transition_type=FilesTransition,
        fingerprint=path_fingerprint,
    )


def _reverse_wire(phase: str, payload: BaseModel, peer: OwnerPeerBinding) -> A11OwnerWire:
    from .analysis.native_import import NativeImportTransition

    return _encode_reverse_wire(phase, payload, peer, transition_type=NativeImportTransition)


def _default_a11_owner_wire(
    owner: A11EffectOwner, phase: str, payload: BaseModel, *, peer: VerifiedOwnerRecipient
) -> A11OwnerWire:
    return accepted_a11_owner_wire(
        owner,
        phase,
        payload,
        peer=peer,
        adapters=OwnerPayloadAdapters(files=_files_wire, reverse=_reverse_wire),
    )


def accepted_a11_owner_wire[PayloadT: BaseModel](
    owner: A11EffectOwner,
    phase: str,
    payload: PayloadT,
    *,
    peer: VerifiedOwnerRecipient,
    adapters: OwnerPayloadAdapters[PayloadT],
) -> A11OwnerWire:
    """Map only accepted source ABIs; missing proof-dependent phases deny before IO."""
    if not isinstance(payload, BaseModel):
        raise A11OwnerWireNotAccepted("A11_OWNER_TYPED_PAYLOAD_REQUIRED")
    binding = _peer(peer)
    mappers: dict[A11EffectOwner, Callable[[str, PayloadT, OwnerPeerBinding], A11OwnerWire]] = {
        "files": adapters.files,
        "execution": _execution_wire,
        "reverse": adapters.reverse,
        "catalog": _catalog_wire,
    }
    dispatch = mappers.get(owner)
    if dispatch is None:
        raise A11OwnerWireNotAccepted
    return dispatch(phase, payload, binding)
