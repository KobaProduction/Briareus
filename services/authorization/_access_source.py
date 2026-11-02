"""Access-only Project AgentSession operations with signed current owner grants.

No shared SQL session with Identity/Team/Project and no unauthenticated UUID
as authority. Private source only until peer attestation C1-B2/C2 reviewed.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._access_cedar import permits_current_project_grant
from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._platform_persistence import OutboxRow, SecurityAuditRow
from authorization._resource_scope import (
    TrustedResourceOwnerPort,
)
from authorization._session_payloads import resource_payload
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from authorization.application.access_commands import AccessCommandScope, OpenSession
from authorization.application.source_approvals import ResolveSourceElevation
from authorization.application.source_payloads import (
    ElevationResolutionPayload,
    SessionRevocationPayload,
)
from authorization.application.source_receipts import (
    SourceElevationRequested,
    SourceElevationResolved,
    SourceSessionOpened,
    SourceSessionRevoked,
)
from authorization.domain.resource_scopes import canonical_grants
from authorization.domain.sessions import SessionResourceGrant
from authorization.infrastructure.journal_records import AccessMutationEvent
from authorization.infrastructure.session_fingerprints import (
    ElevationFingerprint,
    OpenSessionFingerprint,
    ResolutionFingerprint,
    SessionFingerprint,
)
from authorization.infrastructure.session_grant_storage import StoredSessionPermissions
from authorization.infrastructure.source_approvals import SqlSourceApprovalRepository
from authorization.presentation.session_errors import session_errors
from common.infrastructure.audit_records import OperationAudit
from common.owner_contracts import (
    CurrentOwnerAuthorityPort,
    OwnerCommandDTO,
    OwnerProofAuthority,
    SignedOwnerProofs,
    require_online_owner_decision,
    require_signed_payload,
)
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput

_NORMAL = timedelta(hours=24)
_ALLOWED = frozenset(
    {
        "files.read",
        "files.write",
        "project.metadata.read",
        "terminal.execute",
        "web.access",
        "analysis.import",
        "agents.manage",
        "integrations.use",
        "variables.use",
        "integrations.manage",
        "variables.manage",
    }
)
_BASIC = frozenset({"files.read", "project.metadata.read"})


class AccessSourceService:
    def __init__(
        self,
        db: PlatformDatabase,
        authority: OwnerProofAuthority,
        *,
        encryption_key: SecretStr,
        current_owners: CurrentOwnerAuthorityPort,
        resource_owner: TrustedResourceOwnerPort | None = None,
    ) -> None:
        if db.engine.url.database != "briareus_access":
            raise RuntimeError("Access cannot use another owner database")
        if current_owners is None:
            raise RuntimeError("online owner authority cannot be omitted")
        self.current_owners = current_owners
        self.resource_owner = resource_owner
        self.db = db
        self.authority = authority
        self.commands = IdempotentCommandExecutor(db, encryption_key.get_secret_value())

    async def _verify(
        self,
        tx: AsyncSession,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        existing: bool = False,
    ) -> None:
        initial = self.authority.require_current(request, proofs)
        decision = await require_online_owner_decision(self.authority, self.current_owners, request)
        if (
            initial.identity_epoch != decision.identity_epoch
            or initial.control_epoch != decision.control_epoch
            or initial.access_epoch != decision.access_epoch
        ):
            raise AccessDenied("owner source epochs changed since original signature")
        if request.target_owner != "access" or decision.request != request:
            raise AccessDenied("signed Access command owner mismatch")
        if existing:
            row = await tx.scalar(
                select(ProjectAgentSessionRow)
                .where(
                    ProjectAgentSessionRow.session_uuid == request.session_uuid,
                    ProjectAgentSessionRow.project_id == request.project_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or row.version != request.expected_access_revision
                or row.status != "active"
                or row.hard_expires_at <= datetime.now(UTC)
            ):
                raise AccessDenied("AgentSession no longer current")

    @staticmethod
    def _audit(tx: AsyncSession, request: OwnerCommandDTO, action: str, target: UUID) -> None:
        tx.add(
            SecurityAuditRow(
                actor_id=request.caller_user_id,
                project_id=request.project_id,
                action=action,
                object_id=str(target),
                details=OperationAudit(operation_uuid=request.operation_uuid),
            )
        )
        tx.add(
            OutboxRow(
                event_name=action,
                event_payload=AccessMutationEvent(
                    operation_uuid=request.operation_uuid,
                    project_id=request.project_id,
                    entity_id=target,
                ),
            )
        )

    async def open_normal(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        elevation_policy: str = "requestable",
        label: str | None = None,
    ) -> CommandOutcome[SourceSessionOpened]:
        if request.operation != "session.open" or elevation_policy not in {"fixed", "requestable"}:
            raise InvalidInput("unapproved normal AgentSession policy")
        require_signed_payload(
            request, asdict(OpenSession(elevation_policy=elevation_policy, label=label))
        )
        if label is not None and (not (1 <= len(label) <= 128) or any(ord(c) < 32 for c in label)):
            raise InvalidInput("AgentSession label is invalid")

        async def checked(tx: AsyncSession) -> None:
            await self._verify(tx, request, proofs)

        async def command(tx: AsyncSession) -> CommandOutcome[SourceSessionOpened]:
            if await tx.get(ProjectAgentSessionRow, request.session_uuid) is not None:
                raise Conflict("AgentSession UUID already assigned")
            now = datetime.now(UTC)
            row = ProjectAgentSessionRow(
                session_uuid=request.session_uuid,
                project_id=request.project_id,
                created_by_principal_id=request.caller_user_id,
                grants=StoredSessionPermissions(tuple(sorted(_BASIC))),
                is_elevated=False,
                elevation_policy=elevation_policy,
                label=label,
                status="active",
                version=1,
                created_at=now,
                hard_expires_at=now + _NORMAL,
            )
            tx.add(row)
            self._audit(tx, request, "session.opened", row.session_uuid)
            return CommandOutcome(
                201,
                SourceSessionOpened(
                    session_uuid=str(row.session_uuid),
                    project_id=str(row.project_id),
                    expires_at=row.hard_expires_at.isoformat(),
                    revision=row.version,
                ),
            )

        return await self.commands.execute(
            actor_scope=str(request.caller_user_id),
            project_scope=str(request.project_id),
            operation=request.operation,
            key=request.idempotency_key,
            request=OpenSessionFingerprint(
                uuid=request.session_uuid,
                payload_sha256=request.payload_sha256,
                policy=elevation_policy,
                label=label,
            ),
            command=command,
            reauthorize=checked,
            response_model=SourceSessionOpened,
        )

    async def revoke(
        self, request: OwnerCommandDTO, proofs: SignedOwnerProofs
    ) -> CommandOutcome[SourceSessionRevoked]:
        if request.operation != "session.revoke":
            raise InvalidInput("unexpected Access operation")
        require_signed_payload(request, asdict(SessionRevocationPayload()))

        async def checked(tx: AsyncSession) -> None:
            await self._verify(tx, request, proofs, existing=True)

        async def command(tx: AsyncSession) -> CommandOutcome[SourceSessionRevoked]:
            row = await tx.scalar(
                select(ProjectAgentSessionRow)
                .where(ProjectAgentSessionRow.session_uuid == request.session_uuid)
                .with_for_update()
            )
            if row is None or row.project_id != request.project_id:
                raise AccessDenied("AgentSession not found in verified Project")
            row.status = "revoked"
            row.revoked_at = datetime.now(UTC)
            row.version += 1
            self._audit(tx, request, "session.revoked", row.session_uuid)
            return CommandOutcome(
                200,
                SourceSessionRevoked(
                    session_uuid=str(row.session_uuid), version=row.version, status=row.status
                ),
            )

        return await self.commands.execute(
            actor_scope=str(request.caller_user_id),
            project_scope=str(request.project_id),
            operation=request.operation,
            key=request.idempotency_key,
            request=SessionFingerprint(
                uuid=request.session_uuid, payload_sha256=request.payload_sha256
            ),
            command=command,
            reauthorize=checked,
            response_model=SourceSessionRevoked,
        )

    async def request_elevation(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        grants: list[str],
        seconds: int,
        resource_grants: tuple[SessionResourceGrant, ...] | None = None,
    ) -> CommandOutcome[SourceElevationRequested]:
        if (
            request.operation != "session.request_elevation"
            or not 1 <= seconds <= 300
            or not grants
            or not set(grants) <= _ALLOWED
        ):
            raise InvalidInput("invalid elevated operation or TTL/grant scope")
        try:
            resources = canonical_grants(
                resource_grants or (),
                allowed_actions=set(grants),
                project_uuid=None,
            )
        except ValueError as exc:
            raise InvalidInput("invalid scoped resource request") from exc
        resource_models = tuple(resource_payload(scope) for scope in resources)
        fingerprint = ElevationFingerprint(
            uuid=request.session_uuid,
            grants=tuple(sorted(set(grants))),
            seconds=seconds,
            resources=resource_models,
            payload_sha256=request.payload_sha256,
        )
        signed_fields = {"grants", "seconds"}
        if resource_grants is not None:
            signed_fields.add("resources")
        require_signed_payload(request, fingerprint.model_dump(mode="json", include=signed_fields))

        async def checked(tx: AsyncSession) -> None:
            await self._verify(tx, request, proofs, existing=True)

        async def command(tx: AsyncSession) -> CommandOutcome[SourceElevationRequested]:
            base = await tx.get(ProjectAgentSessionRow, request.session_uuid, with_for_update=True)
            if base is None or base.elevation_policy != "requestable" or base.is_elevated:
                raise AccessDenied("base session cannot request elevation")
            approval = SessionApprovalRow(
                id=request.operation_uuid,
                session_uuid=base.session_uuid,
                project_id=base.project_id,
                requested_by_user_id=request.caller_user_id,
                requested_grants=StoredSessionPermissions(tuple(sorted(set(grants))), resources),
                requested_expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
                status="pending",
                version=1,
            )
            tx.add(approval)
            self._audit(tx, request, "session.elevation_requested", approval.id)
            return CommandOutcome(
                202,
                SourceElevationRequested(request_id=str(approval.id), version=1, status="pending"),
            )

        return await self.commands.execute(
            actor_scope=str(request.caller_user_id),
            project_scope=str(request.project_id),
            operation=request.operation,
            key=request.idempotency_key,
            request=fingerprint,
            command=command,
            reauthorize=checked,
            response_model=SourceElevationRequested,
        )

    async def resolve_elevation(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        approval_id: UUID,
        approve: bool,
        allowed_grants: list[str] | None,
        explicit_expansion_confirmation: bool,
        expected_approval_version: int,
    ) -> CommandOutcome[SourceElevationResolved]:
        if (
            request.operation != "session.resolve_elevation"
            or approval_id.version != 4
            or expected_approval_version < 1
            or (allowed_grants is not None and not set(allowed_grants) <= _ALLOWED)
        ):
            raise InvalidInput("invalid approval command or grant")
        require_signed_payload(
            request,
            asdict(
                ElevationResolutionPayload(
                    approval_id=str(approval_id),
                    approve=approve,
                    allowed_grants=sorted(set(allowed_grants))
                    if allowed_grants is not None
                    else None,
                    explicit_expansion_confirmation=explicit_expansion_confirmation,
                    expected_approval_version=expected_approval_version,
                )
            ),
        )

        async def checked(tx: AsyncSession) -> None:
            await self._verify(tx, request, proofs, existing=True)

        async def command(tx: AsyncSession) -> CommandOutcome[SourceElevationResolved]:
            with session_errors():
                repository = SqlSourceApprovalRepository(
                    tx,
                    request.caller_user_id,
                    AccessCommandScope(
                        request.project_id, request.operation_uuid, request.operation, True
                    ),
                    self.resource_owner,
                )
                resolved = await ResolveSourceElevation(repository).execute(
                    actor_uuid=request.caller_user_id,
                    project_uuid=request.project_id,
                    session_uuid=request.session_uuid,
                    approval_uuid=approval_id,
                    expected_version=expected_approval_version,
                    approve=approve,
                    allowed_grants=tuple(allowed_grants) if allowed_grants is not None else None,
                )
                return CommandOutcome(
                    200,
                    SourceElevationResolved(
                        approval_id=str(resolved.request_uuid),
                        status=resolved.status,
                        version=resolved.version,
                        issued_session_uuid=str(resolved.issued_session_uuid)
                        if resolved.issued_session_uuid is not None
                        else None,
                    ),
                )

        return await self.commands.execute(
            actor_scope=str(request.caller_user_id),
            project_scope=str(request.project_id),
            operation=request.operation,
            key=request.idempotency_key,
            request=ResolutionFingerprint(
                uuid=request.session_uuid,
                approval_id=approval_id,
                approve=approve,
                allowed_grants=tuple(allowed_grants) if allowed_grants is not None else None,
                expected_approval_version=expected_approval_version,
                confirmed=explicit_expansion_confirmation,
            ),
            command=command,
            reauthorize=checked,
            response_model=SourceElevationResolved,
        )

    async def verify_current_grant(
        self, request: OwnerCommandDTO, proofs: SignedOwnerProofs
    ) -> bool:
        """Read authoritative Access grant; no token/UUID alone is sufficient."""
        initial = self.authority.require_current(request, proofs)
        fresh = await require_online_owner_decision(self.authority, self.current_owners, request)
        if (
            initial.identity_epoch != fresh.identity_epoch
            or initial.control_epoch != fresh.control_epoch
            or initial.access_epoch != fresh.access_epoch
        ):
            raise AccessDenied("owner authorities no longer current")
        if request.target_owner != "access" or request.operation not in _ALLOWED:
            raise AccessDenied("sensitive operation must be an approved grant")
        async with self.db.transaction() as tx:
            row = await tx.get(ProjectAgentSessionRow, request.session_uuid)
            if (
                row is None
                or row.project_id != request.project_id
                or row.status != "active"
                or row.hard_expires_at <= datetime.now(UTC)
                or row.version != request.expected_access_revision
            ):
                raise AccessDenied("AgentSession grant expired or changed")
            operations = row.grants.operations
            if operations is None or request.operation not in operations:
                raise AccessDenied("AgentSession operation grant missing")
            if not permits_current_project_grant(
                row=row,
                actor_uuid=request.caller_user_id,
                project_uuid=request.project_id,
                operation=request.operation,
                expected_version=request.expected_access_revision,
            ):
                raise AccessDenied("Cedar denies current AgentSession operation")
            return True
