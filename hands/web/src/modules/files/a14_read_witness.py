"""Compatibility API for the canonical shared Files client implementation."""

import asyncio as asyncio
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from typing import Protocol as Protocol
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import model_validator as model_validator

from modules.project_runtime import ProjectAccessDenied as ProjectAccessDenied
from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.project_runtime.owner_authorization import (
    VerifiedOwnerRecipient as VerifiedOwnerRecipient,
)
from modules.project_runtime.owner_effects import OwnerEffectClient as OwnerEffectClient
from modules.project_runtime.owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable
from project_runtime_client.files.read_witness import (
    A14FilesReadPreflight as _SharedA14FilesReadPreflight,
)
from project_runtime_client.files.read_witness import (
    CurrentCommittedFileObject as CurrentCommittedFileObject,
)
from project_runtime_client.files.read_witness import (
    CurrentCommittedFileSourcePort as CurrentCommittedFileSourcePort,
)
from project_runtime_client.files.read_witness import (
    FilesReadBusinessPreimage as FilesReadBusinessPreimage,
)
from project_runtime_client.files.read_witness import TrustedNativeReadPort as TrustedNativeReadPort
from project_runtime_client.files.read_witness import (
    VerifiedNativeFileReadObservation as VerifiedNativeFileReadObservation,
)
from project_runtime_client.files.read_witness import _v4 as _v4

from .a6_signed import canonical_files_path as canonical_files_path
from .a6_signed import path_fingerprint as path_fingerprint
from .infrastructure.read_payloads import FilesReadBusinessPayload as FilesReadBusinessPayload
from .infrastructure.read_payloads import (
    NativeReadBusinessObservation as NativeReadBusinessObservation,
)
from .project_workspace import ProjectFileSnapshot as ProjectFileSnapshot


class A14FilesReadPreflight(_SharedA14FilesReadPreflight):
    async def prepare(
        self,
        invocation: ProjectInvocation,
        *,
        snapshot: ProjectFileSnapshot | None,
        evidence: object,
    ) -> FilesReadBusinessPreimage:
        """Check A14 original operation+native observation; do NOT return bytes.

        The Backend must independently verify the same opaque native evidence
        with its trusted read_observer in the Files-owner transaction, compare
        FileObject CAS/inode/content and return its separately signed result.
        No OwnerEffectClient call or public route is authorized here.
        """
        if self.files_source is None or self.native_verifier is None or evidence is None:
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.action != "files.read"
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or not _v4(scope.request_uuid)
            or not isinstance(snapshot, ProjectFileSnapshot)
            or snapshot._fd < 0
            or snapshot.signed_operation_uuid != scope.request_uuid
            or snapshot.size_bytes > 1048576
            or not snapshot.path
        ):
            raise OwnerEffectUnavailable("A14_FILES_ORIGINAL_SIGNED_SNAPSHOT_REQUIRED")
        initial = await self.authority.require(invocation, "files.read")
        if (
            snapshot.project_id != initial.project_id
            or snapshot.actor_id != initial.actor_id
            or snapshot.agent_session_uuid != initial.session_uuid
            or snapshot.project_access_revision != initial.project_access_revision
            or snapshot.signed_owner_fence != initial.owner_fence
            or snapshot.agent_session_version != initial.decision_version
        ):
            raise ProjectAccessDenied("A14_FILES_SNAPSHOT_GRANT_STALE")
        canonical = canonical_files_path(snapshot.path)
        path_digest = path_fingerprint(canonical)
        peer = await self.effects._recipient(invocation)
        files_source, native_verifier = _required_read_sources(
            self.files_source, self.native_verifier
        )
        try:
            async with asyncio.timeout(min(5.0, self.effects.timeout_seconds)):
                current = await files_source.verified_current_file(
                    invocation, path_digest=path_digest, recipient=peer
                )
                observed = await native_verifier.verified_native_read(
                    evidence, recipient=peer, invocation=invocation, snapshot=snapshot
                )
        except Exception as exc:
            raise OwnerEffectUnavailable(
                "A14_FILES_READ_WITNESS_UNAVAILABLE", unknown=True
            ) from exc
        now = datetime.now(UTC)
        current, observed = _read_observations(current, observed)
        if (
            current.project_id != initial.project_id
            or current.path_digest != path_digest
            or current.size_bytes != snapshot.size_bytes
            or current.content_sha256 != snapshot.sha256
            or observed.operation_uuid != scope.request_uuid
            or observed.project_id != initial.project_id
            or observed.file_id != current.file_id
            or observed.agent_session_uuid != initial.session_uuid
            or observed.actor_user_id != initial.actor_id
            or observed.service_id != peer.service_id
            or observed.instance_uuid != peer.instance_uuid
            or observed.path_digest != path_digest
            or observed.file_version != current.file_version
            or observed.size_bytes != snapshot.size_bytes
            or observed.content_sha256 != snapshot.sha256
            or observed.inode_digest != current.inode_digest
            or not timedelta(0) <= now - observed.observed_at <= timedelta(seconds=5)
            or peer.expires_at <= now
        ):
            raise OwnerEffectUnavailable("A14_FILES_NATIVE_READ_SCOPE_CHANGED", unknown=True)
        try:
            async with asyncio.timeout(min(5.0, self.effects.timeout_seconds)):
                reread = await self.files_source.verified_current_file(
                    invocation, path_digest=path_digest, recipient=peer
                )
                fresh = await self.authority.require(invocation, "files.read")
        except Exception as exc:
            raise OwnerEffectUnavailable("A14_FILES_READ_REREAD_UNAVAILABLE", unknown=True) from exc
        if (
            reread != current
            or fresh.owner_fence != initial.owner_fence
            or fresh.project_access_revision != initial.project_access_revision
            or fresh.project_owner_scope != initial.project_owner_scope
            or fresh.project_owner_id != initial.project_owner_id
            or fresh.actor_id != initial.actor_id
            or fresh.session_uuid != initial.session_uuid
            or fresh.expires_at <= datetime.now(UTC)
            or datetime.now(UTC) - observed.observed_at > timedelta(seconds=5)
        ):
            raise OwnerEffectUnavailable("A14_FILES_READ_REVOKED_BEFORE_SQL", unknown=True)
        return FilesReadBusinessPreimage(
            original_operation_uuid=scope.request_uuid,
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


def _required_read_sources(
    files_source: CurrentCommittedFileSourcePort | None,
    native_verifier: TrustedNativeReadPort | None,
) -> tuple[CurrentCommittedFileSourcePort, TrustedNativeReadPort]:
    if files_source is None or native_verifier is None:
        raise OwnerEffectUnavailable("A14_FILES_NATIVE_C2_AND_OWNER_REQUIRED")
    return files_source, native_verifier


def _read_observations(
    current: object, observed: object
) -> tuple[CurrentCommittedFileObject, VerifiedNativeFileReadObservation]:
    if not isinstance(current, CurrentCommittedFileObject) or not isinstance(
        observed, VerifiedNativeFileReadObservation
    ):
        raise OwnerEffectUnavailable("A14_FILES_NATIVE_READ_SCOPE_CHANGED", unknown=True)
    return current, observed
