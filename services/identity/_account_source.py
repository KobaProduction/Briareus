"""Identity-local privileged account updates with independent Control guard.

No Project/Team database join or service-provided User UUID is authority.
The actual Admin bearer + trusted native peer must be verified by injected
C2 operator transport (unmounted), then Identity rechecks its own live row.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.infrastructure.audit_records import OperationAudit
from common.owner_contracts import TrustedOwnerServicePeerPort
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import UserId
from identity._domain import UserRole
from identity._owner_ledger import OwnerAuditRow, OwnerCommandRow, OwnerOutboxRow
from identity._persistence import InvitationRow, UserRow
from identity._repository import IdentityRepository
from identity.application.account_receipts import AccountChangedReceipt
from identity.infrastructure.owner_event_records import AccountOperationEvent

# Persisted tombstone marker; never a usable password digest.
_DELETED_ACCOUNT_MARKER = "deleted-no-password"


class IdentityAccountCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_uuid: UUID
    actor_id: UUID
    target_user_id: UUID
    action: Literal[
        "identity.suspend",
        "identity.restore",
        "identity.promote",
        "identity.demote",
        "identity.soft_delete",
    ]
    idempotency_key: str = Field(min_length=1, max_length=128)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_actor_version: int = Field(ge=1)
    expected_target_version: int = Field(ge=1)

    @field_validator("operation_uuid", "actor_id", "target_user_id")
    @classmethod
    def _v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Identity command identifiers must be UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedAdminOperator:
    actor_id: UUID
    credential_version: int
    role: Literal["user", "superuser"]
    expires_at: datetime


class TrustedAdminOperatorPort(Protocol):
    async def verify_admin(
        self, evidence: object, *, original: IdentityAccountCommand
    ) -> VerifiedAdminOperator:
        """Must verify active Admin bearer, JTI and credentials at Identity owner."""
        ...


@dataclass(frozen=True, slots=True)
class VerifiedControlUserHold:
    """Versioned Control owner summary; no inferred Team/Project ownership."""

    user_id: UUID
    owned_teams: int
    owned_personal_projects: int
    control_revision: int
    access_fenced: bool
    control_fenced: bool
    verified_at: datetime


class TrustedControlUserHoldPort(Protocol):
    async def verify_no_ownership(
        self, *, user_id: UUID, original_operation_uuid: UUID
    ) -> VerifiedControlUserHold:
        """Requires signed current Control/Access receipts, NEVER read projection."""
        ...


@dataclass(frozen=True, slots=True)
class IdentityAccountOutcome:
    operation_uuid: UUID
    state: Literal["COMMITTED", "UNKNOWN"]
    result: AccountChangedReceipt | None


def _verified_hold(value: object) -> VerifiedControlUserHold:
    if not isinstance(value, VerifiedControlUserHold):
        raise AccessDenied("Identity deletion requires current fenced zero-ownership proof")
    return value


class IdentityAccountSource:
    def __init__(
        self,
        db: PlatformDatabase,
        operator: TrustedAdminOperatorPort | None,
        peer_verifier: TrustedOwnerServicePeerPort | None,
        control_hold: TrustedControlUserHoldPort | None,
        *,
        encrypted_result_key: SecretStr,
    ) -> None:
        if db.engine.url.database != "briareus_identity":
            raise ValueError("Identity account operations require their own owner database")
        if operator is None or peer_verifier is None or control_hold is None:
            raise ValueError("current operator/peer/Control owner ports are mandatory")
        self.db = db
        self.operator = operator
        self.peer_verifier = peer_verifier
        self.control_hold = control_hold
        self.cipher = Fernet(encrypted_result_key.get_secret_value().encode())
        self.users = IdentityRepository()

    async def _operator(
        self,
        command: IdentityAccountCommand,
        *,
        operator_evidence: object,
        peer_evidence: object,
    ) -> VerifiedAdminOperator:
        try:
            import asyncio

            async with asyncio.timeout(3):
                peer = self.peer_verifier.verify_peer(peer_evidence)
                current = await self.operator.verify_admin(operator_evidence, original=command)
            if (
                peer.audience != "briareus:identity"
                or peer.expires_at <= datetime.now(UTC)
                or current.actor_id != command.actor_id
                or current.credential_version != command.expected_actor_version
                or current.role != "superuser"
                or current.expires_at.tzinfo is None
                or current.expires_at <= datetime.now(UTC)
            ):
                raise AccessDenied("current Identity operator authority not verified")
            return current
        except Exception:
            raise AccessDenied("trusted Identity Admin bearer/peer unavailable") from None

    async def _ownership_hold(self, command: IdentityAccountCommand) -> VerifiedControlUserHold:
        try:
            import asyncio

            async with asyncio.timeout(3):
                hold = await self.control_hold.verify_no_ownership(
                    user_id=command.target_user_id,
                    original_operation_uuid=command.operation_uuid,
                )
        except Exception:
            raise AccessDenied("current Control-owned Team/Project impact unavailable") from None
        hold = _verified_hold(hold)
        if (
            hold.user_id != command.target_user_id
            or hold.owned_teams != 0
            or hold.owned_personal_projects != 0
            or hold.control_revision < 1
            or not hold.control_fenced
            or not hold.access_fenced
            or hold.verified_at.tzinfo is None
            or hold.verified_at > datetime.now(UTC)
            or datetime.now(UTC) - hold.verified_at > timedelta(seconds=10)
        ):
            raise AccessDenied("Identity deletion requires current fenced zero-ownership proof")
        return hold

    @staticmethod
    def _validate_payload(command: IdentityAccountCommand) -> None:
        body = {"target_user_id": str(command.target_user_id), "action": command.action}
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != command.payload_sha256:
            raise InvalidInput("signed account effect parameters differ from original intent")

    async def _existing(self, command: IdentityAccountCommand) -> IdentityAccountOutcome | None:
        async with self.db.transaction() as tx:
            row = (
                await tx.scalars(
                    select(OwnerCommandRow)
                    .where(
                        OwnerCommandRow.actor_scope == str(command.actor_id),
                        OwnerCommandRow.project_scope == f"user:{command.target_user_id}",
                        OwnerCommandRow.operation == command.action,
                        OwnerCommandRow.key == command.idempotency_key,
                    )
                    .with_for_update()
                )
            ).first()
            if row is None:
                return None
            if (
                row.operation_uuid != command.operation_uuid
                or row.fingerprint != command.payload_sha256
            ):
                raise Conflict("Identity original Idempotency-Key was reused for a new effect")
            if row.state in {"pending", "unknown"}:
                return IdentityAccountOutcome(row.operation_uuid, "UNKNOWN", None)
            if row.state != "completed" or row.encrypted_outcome is None:
                raise Conflict("Identity command does not have a settled source outcome")
            try:
                result = AccountChangedReceipt.model_validate_json(
                    self.cipher.decrypt(row.encrypted_outcome.encode())
                )
            except (InvalidToken, ValueError, TypeError, UnicodeDecodeError):
                raise Conflict("original Identity result cannot be verified") from None
            return IdentityAccountOutcome(row.operation_uuid, "COMMITTED", result)

    def _previous_outcome(
        self, command: IdentityAccountCommand, previous: OwnerCommandRow
    ) -> IdentityAccountOutcome:
        if (
            previous.operation_uuid != command.operation_uuid
            or previous.fingerprint != command.payload_sha256
        ):
            raise Conflict("Identity command key collision with foreign effect")
        if previous.state in {"pending", "unknown"}:
            return IdentityAccountOutcome(previous.operation_uuid, "UNKNOWN", None)
        if previous.state != "completed" or previous.encrypted_outcome is None:
            raise Conflict("Identity command outcome not settled")
        try:
            body = AccountChangedReceipt.model_validate_json(
                self.cipher.decrypt(previous.encrypted_outcome.encode())
            )
        except (InvalidToken, ValueError, TypeError, UnicodeDecodeError):
            raise Conflict("stored Identity response is not verified") from None
        return IdentityAccountOutcome(previous.operation_uuid, "COMMITTED", body)

    async def _require_account_revocation(
        self, tx: AsyncSession, command: IdentityAccountCommand, target: UserRow
    ) -> None:
        if (
            command.action in {"identity.demote", "identity.suspend", "identity.soft_delete"}
            and target.role == "superuser"
            and target.enabled
        ):
            active = await self.users.list_active_superusers(tx)
            if len(active) <= 1:
                raise Conflict("last active superuser cannot be revoked")

    async def _change_account(
        self,
        tx: AsyncSession,
        command: IdentityAccountCommand,
        target: UserRow,
        hold: VerifiedControlUserHold | None,
    ) -> None:
        await self._require_account_revocation(tx, command, target)
        if command.action == "identity.suspend":
            target.enabled = False
        elif command.action == "identity.restore":
            target.enabled = True
        elif command.action == "identity.promote":
            if not target.enabled:
                raise AccessDenied("disabled User cannot be promoted")
            target.role = UserRole.SUPERUSER.value
        elif command.action == "identity.demote":
            target.role = UserRole.USER.value
        else:
            if hold is None or datetime.now(UTC) - hold.verified_at > timedelta(seconds=10):
                raise AccessDenied("current Control fenced deletion proof expired")
            target.deleted_at = datetime.now(UTC)
            target.enabled = False
            target.username = f"deleted-{target.id}"
            target.password_digest = _DELETED_ACCOUNT_MARKER
        target.credential_version += 1
        target.updated_at = datetime.now(UTC)
        if command.action in {"identity.suspend", "identity.soft_delete"}:
            await tx.execute(
                update(InvitationRow)
                .where(
                    InvitationRow.target_user_id == target.id,
                    InvitationRow.used_at.is_(None),
                    InvitationRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )

    async def apply(
        self,
        command: IdentityAccountCommand,
        *,
        operator_evidence: object,
        peer_evidence: object,
    ) -> IdentityAccountOutcome:
        self._validate_payload(command)
        await self._operator(
            command, operator_evidence=operator_evidence, peer_evidence=peer_evidence
        )
        hold = (
            await self._ownership_hold(command)
            if command.action == "identity.soft_delete"
            else None
        )
        try:
            async with self.db.transaction() as tx:
                await self.users.lock_bootstrap(tx)
                actor = await self.users.get_user(tx, UserId(command.actor_id), lock=True)
                target = await self.users.get_user(tx, UserId(command.target_user_id), lock=True)
                if (
                    actor is None
                    or not actor.enabled
                    or actor.deleted_at is not None
                    or actor.role != "superuser"
                    or actor.credential_version != command.expected_actor_version
                    or target is None
                    or target.deleted_at is not None
                    or target.credential_version != command.expected_target_version
                ):
                    raise AccessDenied("Identity actor or target revision changed")
                previous = (
                    await tx.scalars(
                        select(OwnerCommandRow)
                        .where(
                            OwnerCommandRow.actor_scope == str(command.actor_id),
                            OwnerCommandRow.project_scope == f"user:{command.target_user_id}",
                            OwnerCommandRow.operation == command.action,
                            OwnerCommandRow.key == command.idempotency_key,
                        )
                        .with_for_update()
                    )
                ).first()
                if previous is not None:
                    return self._previous_outcome(command, previous)
                claim = OwnerCommandRow(
                    operation_uuid=command.operation_uuid,
                    actor_scope=str(command.actor_id),
                    project_scope=f"user:{command.target_user_id}",
                    operation=command.action,
                    key=command.idempotency_key,
                    fingerprint=command.payload_sha256,
                    expected_owner_revision=str(command.expected_target_version),
                    state="pending",
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
                tx.add(claim)
                await tx.flush()
                await self._change_account(tx, command, target, hold)
                # A successful SQL commit revokes the former credential-version
                # proof. Fresh Access/Control/JWS peer checks must see it.
                result = AccountChangedReceipt(
                    user_id=target.id,
                    enabled=target.enabled,
                    role=target.role,
                    credential_version=target.credential_version,
                    deleted=target.deleted_at is not None,
                )
                # The operator was verified before the transaction and the
                # current actor is now row-locked in the SAME Identity DB.
                # Avoid a remote C2 callback while an authoritative lock is
                # held; DB-owned credential version is the commit fence.
                claim.state = "completed"
                claim.updated_at = datetime.now(UTC)
                claim.encrypted_outcome = self.cipher.encrypt(
                    json.dumps(
                        result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                    ).encode()
                ).decode()
                tx.add(
                    OwnerAuditRow(
                        operation_uuid=command.operation_uuid,
                        actor_user_id=command.actor_id,
                        project_id=None,
                        action=command.action,
                        object_id=str(target.id),
                        owner_revision=str(target.credential_version),
                        details=OperationAudit(operation_uuid=command.operation_uuid),
                    )
                )
                tx.add(
                    OwnerOutboxRow(
                        operation_uuid=command.operation_uuid,
                        event_name=command.action,
                        owner_revision=str(target.credential_version),
                        event_payload=AccountOperationEvent(
                            user_id=target.id,
                            credential_version=target.credential_version,
                            operation_uuid=command.operation_uuid,
                        ),
                    )
                )
                return IdentityAccountOutcome(command.operation_uuid, "COMMITTED", result)
        except IntegrityError:
            current = await self._existing(command)
            if current is None:
                raise
            return current
