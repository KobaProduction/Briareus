"""Shared Platform Control commands; state adapters remain layout-local."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.infrastructure.audit_records import TeamOperationAudit
from common.infrastructure.owner_event_records import TeamChangedEvent
from common.owner_team_contracts import (
    CurrentTeamOwnerPort,
    SignedTeamProofs,
    TeamOwnerCommandDTO,
    TeamOwnerProofAuthority,
    VerifiedTeamOperation,
    require_current_team,
)
from common.owner_transactions import OwnerCommandOutcome
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects._control_ledger import OwnerAuditRow, OwnerCommandRow, OwnerOutboxRow


class TeamOwnerSource:
    def __init__(
        self,
        db: PlatformDatabase,
        authority: TeamOwnerProofAuthority,
        current: CurrentTeamOwnerPort,
        *,
        encryption_key: SecretStr,
    ) -> None:
        if db.engine.url.database != "briareus_platform" or current is None:
            raise RuntimeError("Team membership must have its own Control database and trust")
        self.db = db
        self.authority = authority
        self.current = current
        self.cipher = Fernet(encryption_key.get_secret_value().encode())

    async def _live(
        self, request: TeamOwnerCommandDTO, proofs: SignedTeamProofs
    ) -> VerifiedTeamOperation:
        initial = self.authority.verify(request, proofs)
        live = await require_current_team(self.authority, self.current, request)
        if (
            initial.actor_role != live.actor_role
            or initial.identity_epoch != live.identity_epoch
            or initial.team_epoch != live.team_epoch
            or initial.access_epoch != live.access_epoch
        ):
            raise AccessDenied("Team current User/owner authority was revoked")
        return live

    async def _target_enabled(self, request: TeamOwnerCommandDTO, target_id: UUID) -> int:
        try:
            import asyncio

            async with asyncio.timeout(3):
                receipt = await self.current.fetch_target_identity(request, target_id)
            return self.authority.verify_target(request, target_id, receipt)
        except Exception:
            raise AccessDenied("target User is not currently signed as active") from None

    async def _status[ResultT: BaseModel](
        self,
        request: TeamOwnerCommandDTO,
        proofs: SignedTeamProofs,
        *,
        response_model: type[ResultT],
    ) -> OwnerCommandOutcome[ResultT] | None:
        await self._live(request, proofs)
        async with self.db.transaction() as tx:
            row = await tx.scalar(
                select(OwnerCommandRow)
                .where(
                    OwnerCommandRow.actor_scope == str(request.caller_user_id),
                    OwnerCommandRow.project_scope == f"team:{request.team_id}",
                    OwnerCommandRow.operation == request.operation,
                    OwnerCommandRow.key == request.idempotency_key,
                )
                .with_for_update()
            )
            if row is None:
                return None
            if (
                row.operation_uuid != request.operation_uuid
                or row.fingerprint != request.payload_sha256
            ):
                raise Conflict("Team command key reused with different signed payload")
            if row.state in {"pending", "unknown"}:
                return OwnerCommandOutcome(row.operation_uuid, "UNKNOWN", None)
            if row.state != "completed" or row.encrypted_outcome is None:
                raise Conflict("Team operation is not verified as completed")
            try:
                body = response_model.model_validate_json(
                    self.cipher.decrypt(row.encrypted_outcome.encode())
                )
            except (InvalidToken, UnicodeDecodeError, ValueError, TypeError):
                raise Conflict("Team original encrypted command result unavailable") from None
            return OwnerCommandOutcome(row.operation_uuid, "COMMITTED", body)

    async def _execute[ResultT: BaseModel](
        self,
        request: TeamOwnerCommandDTO,
        proofs: SignedTeamProofs,
        mutation: Callable[[AsyncSession, VerifiedTeamOperation], Awaitable[ResultT]],
        *,
        event: str,
        subject: UUID,
        response_model: type[ResultT],
    ) -> OwnerCommandOutcome[ResultT]:
        decision = await self._live(request, proofs)
        try:
            async with self.db.transaction() as tx:
                await tx.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": f"briareus:platform:{request.operation_uuid}"},
                )
                await self._require_previous_phases(tx, request)
                row = await tx.scalar(
                    select(OwnerCommandRow)
                    .where(
                        OwnerCommandRow.actor_scope == str(request.caller_user_id),
                        OwnerCommandRow.project_scope == f"team:{request.team_id}",
                        OwnerCommandRow.operation == request.operation,
                        OwnerCommandRow.key == request.idempotency_key,
                    )
                    .with_for_update()
                )
                if row is not None:
                    return self._replay_result(row, request, response_model=response_model)
                row = OwnerCommandRow(
                    operation_uuid=request.operation_uuid,
                    actor_scope=str(request.caller_user_id),
                    project_scope=f"team:{request.team_id}",
                    operation=request.operation,
                    key=request.idempotency_key,
                    fingerprint=request.payload_sha256,
                    expected_owner_revision=str(request.expected_team_revision),
                    state="pending",
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
                tx.add(row)
                await tx.flush()
                result = await mutation(tx, decision)
                if not isinstance(result, response_model):
                    raise InvalidInput("Team mutation returned a different response contract")
                verified = await require_current_team(self.authority, self.current, request)
                if (
                    verified.identity_epoch != decision.identity_epoch
                    or verified.team_epoch != decision.team_epoch
                    or verified.access_epoch != decision.access_epoch
                    or verified.actor_role != decision.actor_role
                ):
                    raise AccessDenied("Team source owner version changed before commit")
                row.state = "completed"
                row.updated_at = datetime.now(UTC)
                row.encrypted_outcome = self.cipher.encrypt(
                    json.dumps(
                        result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                    ).encode()
                ).decode()
                tx.add(
                    OwnerOutboxRow(
                        operation_uuid=request.operation_uuid,
                        event_name=event,
                        owner_revision=str(request.expected_team_revision),
                        event_payload=TeamChangedEvent(
                            team_id=request.team_id,
                            actor_user_id=request.caller_user_id,
                            subject_id=subject,
                            operation_uuid=request.operation_uuid,
                        ),
                    )
                )
                tx.add(
                    OwnerAuditRow(
                        operation_uuid=request.operation_uuid,
                        actor_user_id=request.caller_user_id,
                        project_id=None,
                        action=event,
                        object_id=str(subject),
                        owner_revision=str(request.expected_team_revision),
                        details=TeamOperationAudit(
                            team_id=request.team_id,
                            operation_uuid=request.operation_uuid,
                        ),
                    )
                )
                return OwnerCommandOutcome(request.operation_uuid, "COMMITTED", result)
        except IntegrityError:
            previous = await self._status(request, proofs, response_model=response_model)
            if previous is None:
                raise
            return previous

    async def _require_previous_phases(
        self, tx: AsyncSession, request: TeamOwnerCommandDTO
    ) -> None:
        previous_phases = list(
            await tx.scalars(
                select(OwnerCommandRow)
                .where(
                    OwnerCommandRow.operation_uuid == request.operation_uuid,
                )
                .with_for_update()
            )
        )
        for phase_row in previous_phases:
            if (
                phase_row.actor_scope != str(request.caller_user_id)
                or phase_row.project_scope != f"team:{request.team_id}"
                or phase_row.key != request.idempotency_key
            ):
                raise AccessDenied("Team original UUID must retain actor, Team and key")
            if phase_row.operation != request.operation and phase_row.state != "completed":
                raise AccessDenied("Team phase cannot bypass unresolved previous command")

    def _replay_result[ResultT: BaseModel](
        self,
        row: OwnerCommandRow,
        request: TeamOwnerCommandDTO,
        *,
        response_model: type[ResultT],
    ) -> OwnerCommandOutcome[ResultT]:
        if (
            row.fingerprint != request.payload_sha256
            or row.operation_uuid != request.operation_uuid
        ):
            raise Conflict("Team Idempotency-Key has a different original intent")
        if row.state in {"pending", "unknown"}:
            return OwnerCommandOutcome(row.operation_uuid, "UNKNOWN", None)
        if row.state != "completed" or row.encrypted_outcome is None:
            raise Conflict("Team original command has no completed outcome")
        try:
            replay = response_model.model_validate_json(
                self.cipher.decrypt(row.encrypted_outcome.encode())
            )
        except (InvalidToken, UnicodeDecodeError, ValueError, TypeError):
            raise Conflict("Team original encrypted result unavailable") from None
        return OwnerCommandOutcome(row.operation_uuid, "COMMITTED", replay)
