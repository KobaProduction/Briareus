"""Unmounted Rauthy/Platform/Access Files-read consumer, without legacy epochs.

The authority port is deliberately not implemented here. A trusted
composition root must bind it to genuine resource-token verification,
current Platform membership, private Access peer and a real Files root
owner. Neither caller JSON nor a V2 {allowed:true} constructs that scope.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from project_runtime_client.domain.owner_wire import uuid_v4 as _is_v4_uuid
from service_runtime._authority_binding import _OptionalAuthorityBinding

from ._fd_snapshot import FilesNodeStamp, FilesReadObservation, HeldFilesRead, open_confined_read
from ._lease_deadline import ReadLeaseDeadline
from ._read_adapter import FilesMcpReadUnavailable, FilesReadArguments, FilesReadContent
from ._read_scope import FilesReadSelector

_OWNER_SCOPE_TIMEOUT = 10


@dataclass(frozen=True, slots=True)
class NativeFilesReadRequest:
    """Server-side request selectors, not proof that the actor owns them."""

    request_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    expected_grant_revision: int
    arguments: FilesReadArguments

    def __post_init__(self) -> None:
        if not isinstance(self.arguments, FilesReadArguments):
            raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
        if (
            any(
                not _is_v4_uuid(v)
                for v in (self.request_uuid, self.project_uuid, self.agent_session_uuid)
            )
            or type(self.expected_grant_revision) is not int
            or (not 1 <= self.expected_grant_revision <= 2**63 - 1)
        ):
            raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")

    @property
    def selector(self) -> FilesReadSelector:
        return FilesReadSelector(self.project_uuid, self.arguments)

    @property
    def request_fingerprint(self) -> str:
        preimage = json.dumps(
            [
                str(self.request_uuid),
                str(self.project_uuid),
                str(self.agent_session_uuid),
                self.expected_grant_revision,
                self.selector.resource_id,
                self.arguments.path,
                self.arguments.max_bytes,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(b"briareus-native-files-read-v1\0" + preimage).hexdigest()


class NativeFilesReadScope(Protocol):
    """Private preauthorized scope, supplied by a genuine owner adapter only.

    The adapter independently checks the ORIGINAL signed caller, audience,
    exact request fingerprint/selector and current revisions before entry.
    root_fd stays live until context exit, belongs to the current Files
    Project root, and may not come from MCP arguments. owner_revision is
    from the actual Files mapping authority, never inferred from inode or
    fabricated from absent Identity epochs. root_observation is local OS
    evidence, not an authority token. Context exit must preserve the final
    current-state barrier and must deny if its authority was revoked.
    """

    request: NativeFilesReadRequest
    root_fd: int
    root_observation: FilesNodeStamp
    owner_revision: int
    expires_at: datetime
    # Set only from the independently checked after_read reply. Release
    # must satisfy BOTH this deadline and the unchanged original lease.
    final_expiry: datetime | None

    async def revalidate(self, observation: FilesReadObservation) -> object:
        """Fresh membership/grant + same Files mapping/revision; raise on denial.

        Verify the scope's original signed token/peer/request binding again
        and that the current owner root still names the held descriptor.
        No cached Permit or observation-to-permission conversion. Return
        None only after authoritative checks, not an unverified bool.
        """
        ...


class NativeFilesReadAuthority(Protocol):
    def open_read(
        self, request: NativeFilesReadRequest
    ) -> AbstractAsyncContextManager[NativeFilesReadScope]:
        """Private authenticated authority; no default implementation/fallback."""
        ...


async def _join_io[T](task: asyncio.Task[T]) -> T:
    # Filesystem worker cannot be canceled halfway while its FD is in use.
    # Drain it before releasing the owner's scope, then propagate cancellation.
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(BaseException):
            result = task.result()
            if isinstance(result, HeldFilesRead):
                result.close()
        raise


def _check_scope(scope: NativeFilesReadScope, request: NativeFilesReadRequest) -> None:
    now = datetime.now(UTC)
    if not isinstance(scope.root_observation, FilesNodeStamp):
        raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_INVALID")
    if not isinstance(scope.expires_at, datetime):
        raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_INVALID")
    if (
        scope.request != request
        or type(scope.root_fd) is not int
        or scope.root_fd < 0
        or (type(scope.owner_revision) is not int)
        or (not 1 <= scope.owner_revision <= 2**63 - 1)
        or (scope.expires_at.tzinfo is None)
        or (not now < scope.expires_at <= now + timedelta(seconds=5))
    ):
        raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_INVALID")


def _require_final_expiry(final_expiry: datetime | None) -> datetime:
    if not isinstance(final_expiry, datetime):
        raise FilesMcpReadUnavailable("FILES_NATIVE_FINAL_PROOF_INVALID")
    if final_expiry.tzinfo is None or not datetime.now(UTC) < final_expiry <= datetime.now(
        UTC
    ) + timedelta(seconds=5):
        raise FilesMcpReadUnavailable("FILES_NATIVE_FINAL_PROOF_INVALID")
    return final_expiry


class UnmountedNativeFilesRead(_OptionalAuthorityBinding[NativeFilesReadAuthority]):
    async def execute(self, request: NativeFilesReadRequest) -> FilesReadContent:
        authority = self._authority
        if authority is None:
            raise FilesMcpReadUnavailable("FILES_NATIVE_AUTHORITY_UNAVAILABLE")
        if not isinstance(request, NativeFilesReadRequest):
            raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
        snapshot: HeldFilesRead | None = None
        validated = False
        try:
            async with asyncio.timeout(_OWNER_SCOPE_TIMEOUT), authority.open_read(request) as scope:
                _check_scope(scope, request)
                initial_lease = ReadLeaseDeadline.capture(scope.expires_at, maximum_seconds=5)
                revision, root, expiry = (
                    scope.owner_revision,
                    scope.root_observation,
                    scope.expires_at,
                )
                snapshot = await _join_io(
                    asyncio.create_task(
                        asyncio.to_thread(
                            open_confined_read,
                            scope.root_fd,
                            root,
                            request.arguments,
                        )
                    )
                )
                initial_lease.check()
                if await scope.revalidate(snapshot.observation) is not None:
                    raise FilesMcpReadUnavailable("FILES_NATIVE_REVALIDATION_INVALID")
                final_expiry = scope.final_expiry
                final_expiry = _require_final_expiry(final_expiry)
                final_lease = ReadLeaseDeadline.capture(final_expiry, maximum_seconds=5)
                initial_lease.check()
                _check_scope(scope, request)
                if (scope.owner_revision, scope.root_observation, scope.expires_at) != (
                    revision,
                    root,
                    expiry,
                ):
                    raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_CHANGED")
                validated = True
            # A context manager must never turn a suppressed verification
            # failure into a successful read merely by returning normally.
            _require_not_cancelled()
            if not validated or snapshot is None:
                raise FilesMcpReadUnavailable("FILES_NATIVE_READ_UNVALIDATED")
            initial_lease.check()
            final_lease.check()
            # Scope exit can fail/deny too. Never return bytes inside the
            # authority context; also stop if its lease expired during exit.
            if (
                scope.final_expiry != final_expiry
                or scope.expires_at != expiry
                or datetime.now(UTC) >= min(expiry, final_expiry)
            ):
                raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_EXPIRED")
            if (scope.request, scope.owner_revision, scope.root_observation) != (
                request,
                revision,
                root,
            ):
                raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_CHANGED")
            # The owner may have awaited during context exit. Check the
            # retained descriptor/path AFTER that boundary as well, then
            # recheck both proof deadlines before exposing any bytes.
            await _join_io(asyncio.create_task(asyncio.to_thread(snapshot.validate_current)))
            if datetime.now(UTC) >= min(expiry, final_expiry):
                raise FilesMcpReadUnavailable("FILES_NATIVE_SCOPE_EXPIRED")
            initial_lease.check()
            final_lease.check()
            result = FilesReadContent.from_verified_bytes(request.arguments, snapshot.payload)
            initial_lease.check()
            final_lease.check()
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            raise FilesMcpReadUnavailable("FILES_NATIVE_READ_UNAVAILABLE") from None
        finally:
            if snapshot is not None:
                snapshot.close()


def _require_not_cancelled() -> None:
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError
