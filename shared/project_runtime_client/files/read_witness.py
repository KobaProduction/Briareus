"""A14 Files read witness preflight: no native signer, SQL, or public tool.

This consumer can bind a separately trusted Files FileObject source and a C2
signed native FD witness. It only prepares the exact business payload that
Backend A14 must independently verify inside its Files-owner SQL transaction.
A prepared payload is NOT a read permit, credential, or OS authority.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from project_runtime_client.application.authorization import ProjectRuntimeAuthority
from project_runtime_client.domain.authorization import (
    ProjectAccessDenied,
    ProjectInvocation,
    ProjectPermit,
)
from project_runtime_client.domain.owner_wire import uuid_v4 as _uuid_v4_source
from project_runtime_client.files.domain.read_witness import (
    FileContentBinding,
    NativeReadBinding,
    ReadWitnessChanged,
    ReadWitnessExpectation,
    ReadWitnessObservation,
    require_current_witness,
)
from project_runtime_client.files.read_payloads import (
    FilesReadBusinessPayload,
    NativeReadBusinessObservation,
)
from project_runtime_client.files.signed import canonical_files_path, path_fingerprint
from project_runtime_client.files.workspace import ProjectFileSnapshot
from project_runtime_client.owner_authorization import VerifiedOwnerRecipient
from project_runtime_client.owner_effects import OwnerEffectUnavailable

_v4 = _uuid_v4_source
del _uuid_v4_source


class CurrentCommittedFileObject(BaseModel):
    """Only a signed, current Files owner port may supply this projection."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project_id: UUID
    file_id: UUID
    path_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_version: int = Field(ge=1)
    size_bytes: int = Field(ge=0, le=1048576)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inode_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_identity(self) -> CurrentCommittedFileObject:
        if not _v4(self.project_id) or not _v4(self.file_id):
            raise ValueError("current Files owner IDs must be UUIDv4")
        return self


class VerifiedNativeFileReadObservation(BaseModel):
    """Exactly the fields accepted by A14 VerifiedNativeFileReadObservation.

    Structural validation does NOT verify an OS signature. Only the injected
    trusted C2 native port below may return this after independently checking
    the signer, source descriptor, UID, private mount and operation recipient.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_uuid: UUID
    project_id: UUID
    file_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    service_id: UUID
    instance_uuid: UUID
    path_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_version: int = Field(ge=1)
    size_bytes: int = Field(ge=0, le=1048576)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inode_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mount_scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_uid: int = Field(gt=0)
    observed_at: datetime

    @model_validator(mode="after")
    def check_identity_and_time(self) -> VerifiedNativeFileReadObservation:
        if (
            not all(
                _v4(value)
                for value in (
                    self.operation_uuid,
                    self.project_id,
                    self.file_id,
                    self.agent_session_uuid,
                    self.actor_user_id,
                    self.service_id,
                    self.instance_uuid,
                )
            )
            or self.observed_at.tzinfo is None
        ):
            raise ValueError("A14 native Files read signed source scope invalid")
        return self


class CurrentCommittedFileSourcePort(Protocol):
    """Independent signed Files-owner lookup, not an MCP/client FileObject."""

    async def verified_current_file(
        self,
        invocation: ProjectInvocation,
        *,
        path_digest: str,
        recipient: VerifiedOwnerRecipient,
    ) -> CurrentCommittedFileObject: ...


class TrustedNativeReadPort(Protocol):
    """Verify genuine C2 signed OS FD/UID/mount evidence without creating it."""

    async def verified_native_read(
        self,
        evidence: object,
        *,
        recipient: VerifiedOwnerRecipient,
        invocation: ProjectInvocation,
        snapshot: ProjectFileSnapshot,
    ) -> VerifiedNativeFileReadObservation: ...


@dataclass(frozen=True, slots=True)
class FilesReadBusinessPreimage:
    """Backend A14 canonical JSON body; NEVER a signed or completed receipt."""

    original_operation_uuid: UUID
    file_object: CurrentCommittedFileObject
    observation: VerifiedNativeFileReadObservation
    business_payload: FilesReadBusinessPayload


def _original_operation(
    invocation: ProjectInvocation, snapshot: ProjectFileSnapshot | None
) -> UUID:
    scope = invocation.operation_scope
    if not isinstance(snapshot, ProjectFileSnapshot):
        raise OwnerEffectUnavailable("A14_FILES_ORIGINAL_SIGNED_SNAPSHOT_REQUIRED")
    if (
        scope is None
        or scope.action != "files.read"
        or scope.project_id != invocation.project_id
        or (scope.agent_session_uuid != invocation.session_uuid)
        or (not _v4(scope.request_uuid))
        or (snapshot._fd < 0)
        or (snapshot.signed_operation_uuid != scope.request_uuid)
        or (snapshot.size_bytes > 1048576)
        or (not snapshot.path)
    ):
        raise OwnerEffectUnavailable("A14_FILES_ORIGINAL_SIGNED_SNAPSHOT_REQUIRED")
    return scope.request_uuid


def _require_snapshot_current(snapshot: ProjectFileSnapshot, initial: ProjectPermit) -> None:
    if (
        snapshot.project_id != initial.project_id
        or snapshot.actor_id != initial.actor_id
        or snapshot.agent_session_uuid != initial.session_uuid
        or snapshot.project_access_revision != initial.project_access_revision
        or snapshot.signed_owner_fence != initial.owner_fence
        or snapshot.agent_session_version != initial.decision_version
    ):
        raise ProjectAccessDenied("A14_FILES_SNAPSHOT_GRANT_STALE")


def _require_witness(
    snapshot: ProjectFileSnapshot,
    initial: ProjectPermit,
    current: CurrentCommittedFileObject,
    observed: VerifiedNativeFileReadObservation,
    peer: VerifiedOwnerRecipient,
    operation: UUID,
    path_digest: str,
) -> None:
    if not isinstance(current, CurrentCommittedFileObject):
        raise OwnerEffectUnavailable("A14_FILES_NATIVE_READ_SCOPE_CHANGED", unknown=True)
    if not isinstance(observed, VerifiedNativeFileReadObservation):
        raise OwnerEffectUnavailable("A14_FILES_NATIVE_READ_SCOPE_CHANGED", unknown=True)
    expected = ReadWitnessExpectation(
        FileContentBinding(initial.project_id, path_digest, snapshot.size_bytes, snapshot.sha256),
        NativeReadBinding(
            operation,
            initial.project_id,
            current.file_id,
            initial.session_uuid,
            initial.actor_id,
            peer.service_id,
            peer.instance_uuid,
            path_digest,
            current.file_version,
            snapshot.size_bytes,
            snapshot.sha256,
            current.inode_digest,
        ),
    )
    actual = ReadWitnessObservation(
        FileContentBinding(
            current.project_id, current.path_digest, current.size_bytes, current.content_sha256
        ),
        NativeReadBinding(
            observed.operation_uuid,
            observed.project_id,
            observed.file_id,
            observed.agent_session_uuid,
            observed.actor_user_id,
            observed.service_id,
            observed.instance_uuid,
            observed.path_digest,
            observed.file_version,
            observed.size_bytes,
            observed.content_sha256,
            observed.inode_digest,
        ),
        observed.observed_at,
        peer.expires_at,
    )
    try:
        require_current_witness(expected, actual, datetime.now(UTC))
    except ReadWitnessChanged as exc:
        raise OwnerEffectUnavailable(str(exc), unknown=True) from exc


def _require_read_continuity(
    initial: ProjectPermit,
    fresh: ProjectPermit,
    current: CurrentCommittedFileObject,
    reread: CurrentCommittedFileObject,
    observed_at: datetime,
) -> None:
    if (
        reread != current
        or fresh.owner_fence != initial.owner_fence
        or fresh.project_access_revision != initial.project_access_revision
        or fresh.project_owner_scope != initial.project_owner_scope
        or fresh.project_owner_id != initial.project_owner_id
        or fresh.actor_id != initial.actor_id
        or fresh.session_uuid != initial.session_uuid
        or fresh.expires_at <= datetime.now(UTC)
        or datetime.now(UTC) - observed_at > timedelta(seconds=5)
    ):
        raise OwnerEffectUnavailable("A14_FILES_READ_REVOKED_BEFORE_SQL", unknown=True)


class FilesReadEffectsPort(Protocol):
    timeout_seconds: float

    async def _recipient(self, invocation: ProjectInvocation) -> VerifiedOwnerRecipient: ...


class A14FilesReadPreflight:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        effects: FilesReadEffectsPort,
        *,
        files_source: CurrentCommittedFileSourcePort | None = None,
        native_verifier: TrustedNativeReadPort | None = None,
    ) -> None:
        self.authority = authority
        self.effects = effects
        self.files_source = files_source
        self.native_verifier = native_verifier

    async def prepare(
        self,
        invocation: ProjectInvocation,
        *,
        snapshot: ProjectFileSnapshot,
        evidence: object,
    ) -> FilesReadBusinessPreimage:
        """Check A14 original operation+native observation; do NOT return bytes.

        The Backend must independently verify the same opaque native evidence
        with its trusted read_observer in the Files-owner transaction, compare
        FileObject CAS/inode/content and return its separately signed result.
        No OwnerEffectClient call or public route is authorized here.
        """
        if self.files_source is None:
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
        if self.native_verifier is None or evidence is None:
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
        operation = _original_operation(invocation, snapshot)
        initial = await self.authority.require(invocation, "files.read")
        _require_snapshot_current(snapshot, initial)
        canonical = canonical_files_path(snapshot.path)
        path_digest = path_fingerprint(canonical)
        peer = await self.effects._recipient(invocation)
        if self.files_source is None:
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
        if self.native_verifier is None:
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
        try:
            async with asyncio.timeout(min(5.0, self.effects.timeout_seconds)):
                current = await self.files_source.verified_current_file(
                    invocation, path_digest=path_digest, recipient=peer
                )
                observed = await self.native_verifier.verified_native_read(
                    evidence, recipient=peer, invocation=invocation, snapshot=snapshot
                )
        except Exception as exc:
            raise OwnerEffectUnavailable(
                "A14_FILES_READ_WITNESS_UNAVAILABLE", unknown=True
            ) from exc
        _require_witness(snapshot, initial, current, observed, peer, operation, path_digest)
        try:
            async with asyncio.timeout(min(5.0, self.effects.timeout_seconds)):
                reread = await self.files_source.verified_current_file(
                    invocation, path_digest=path_digest, recipient=peer
                )
                fresh = await self.authority.require(invocation, "files.read")
        except Exception as exc:
            raise OwnerEffectUnavailable("A14_FILES_READ_REREAD_UNAVAILABLE", unknown=True) from exc
        _require_read_continuity(initial, fresh, current, reread, observed.observed_at)
        return FilesReadBusinessPreimage(
            original_operation_uuid=operation,
            file_object=current,
            observation=observed,
            business_payload=FilesReadBusinessPayload(
                file_id=str(current.file_id),
                expected_file_version=current.file_version,
                path_digest=path_digest,
                service_id=str(peer.service_id),
                instance_uuid=str(peer.instance_uuid),
                native_observation=NativeReadBusinessObservation(
                    content_sha256=observed.content_sha256,
                    size_bytes=observed.size_bytes,
                    inode_digest=observed.inode_digest,
                    mount_scope_digest=observed.mount_scope_digest,
                    verified_uid=observed.verified_uid,
                    observed_at=observed.observed_at.isoformat(),
                ),
            ),
        )
