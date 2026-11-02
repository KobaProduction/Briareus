"""Durable original-login intent and completion in the isolated legacy Identity database."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from common.platform_db import PlatformDatabase
from common.platform_errors import AuthenticationRequired
from identity._owner_ledger import OwnerCommandRow
from identity.application.private_login import (
    IdentitySourceUnavailable,
    VerifiedIdentityLoginAdmission,
)


@dataclass(frozen=True)
class SqlOriginalLoginLedger:
    database: PlatformDatabase
    identity_login_pepper: bytes

    async def _reserve_original_login(
        self,
        *,
        original_uuid: UUID,
        username: str,
        password: SecretStr,
        admission: VerifiedIdentityLoginAdmission,
    ) -> UUID:
        """Durably consume one original pre-auth operation before issuing a JTI.

        An ambiguous response must never mint another bearer for the same
        original operation. Existing Identity commands migration owns this
        table, and no secret or reversible password fingerprint is persisted.
        """
        if original_uuid.version != 4:
            raise AuthenticationRequired("canonical original login UUID required")
        digest = hmac.new(
            self.identity_login_pepper,
            b"identity-login-v1\0"
            + username.encode("utf-8")
            + b"\0"
            + password.get_secret_value().encode("utf-8")
            + b"\0"
            + admission.source_fingerprint.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        receipt_id = uuid4()
        now = datetime.now(UTC)
        statement = (
            insert(OwnerCommandRow)
            .values(
                id=receipt_id,
                operation_uuid=original_uuid,
                actor_scope="identity:preauth",
                project_scope="none",
                operation="identity.login",
                key=str(original_uuid),
                fingerprint=digest,
                expected_owner_revision="identity-login-v1",
                state="pending",
                encrypted_outcome=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=1),
            )
            .on_conflict_do_nothing()
            .returning(OwnerCommandRow.id)
        )
        async with self.database.transaction() as tx:
            if await tx.scalar(statement) is None:
                raise IdentitySourceUnavailable(
                    "original Identity login already consumed; outcome may be unknown"
                )
        return receipt_id

    async def _complete_original_login(self, receipt_id: UUID) -> None:
        async with self.database.transaction() as tx:
            result = await tx.execute(
                update(OwnerCommandRow)
                .where(OwnerCommandRow.id == receipt_id, OwnerCommandRow.state == "pending")
                .values(state="completed", updated_at=datetime.now(UTC))
                .returning(OwnerCommandRow.id)
            )
            if result.scalar_one_or_none() != receipt_id:
                raise IdentitySourceUnavailable("original Identity login status unavailable")
