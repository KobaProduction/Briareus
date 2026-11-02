"""Identity application operations against an isolated new SQL database."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from urllib.parse import quote
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from common.credential_primitives import hash_password, random_token
from common.platform_db import PlatformDatabase
from common.platform_errors import (
    InvalidInput,
)
from common.platform_ids import UserId
from identity._domain import User
from identity._operator_channel import UnixFirstAdminOperatorGate
from identity._owner_ledger import OwnerAuditRow, OwnerOutboxRow
from identity._repository import IdentityRepository
from identity._settings import IdentityLinkSettings
from identity.application.accounts import LegacyAccountLifecycle
from identity.application.authentication import AuthenticateLegacyUser
from identity.application.first_admin import IssueLegacyFirstAdminSetup
from identity.application.invitations import LegacyIdentityInvitations
from identity.application.limited_login import AuthenticateLimitedLegacyUser
from identity.application.registration import RegisterLegacyUser
from identity.infrastructure.accounts import SqlAccountTransactions
from identity.infrastructure.audit_records import AccountSecurityAudit
from identity.infrastructure.authentication import SqlAuthenticationTransactions
from identity.infrastructure.credentials import LegacyCredentials
from identity.infrastructure.first_admin import LegacySetupOperator, SqlSetupTransactions
from identity.infrastructure.invitations import LegacyInvitationLinks, SqlInvitationTransactions
from identity.infrastructure.limited_login import SqlLoginTransactions
from identity.infrastructure.registration import (
    SqlRegistrationTransactions,
)

utcnow = partial(datetime.now, UTC)


class IdentityService:
    def __init__(
        self,
        database: PlatformDatabase,
        settings: IdentityLinkSettings,
        *,
        operator_gate: UnixFirstAdminOperatorGate | None = None,
    ) -> None:
        if database.engine.url.database != "briareus_identity":
            raise RuntimeError("Identity operations require briareus_identity, not global DB")
        self.database = database
        self.repository = IdentityRepository()
        self._operator_gate = operator_gate
        self.admin_ui_public_url = settings.admin_ui_public_url
        self._dummy_password_digest = hash_password(random_token())

    def _link(self, kind: str, raw_token: str) -> str:
        if not self.admin_ui_public_url:
            raise InvalidInput("ADMIN_UI_PUBLIC_URL required when issuing an invitation/reset URL")
        return f"{self.admin_ui_public_url}?{kind}={quote(raw_token)}"

    @asynccontextmanager
    async def _transaction(self, existing: AsyncSession | None) -> AsyncIterator[AsyncSession]:
        if existing is not None:
            yield existing
        else:
            async with self.database.transaction() as session:
                yield session

    @staticmethod
    def _record_local_security_event(
        tx: AsyncSession,
        *,
        actor_id: UserId | None,
        target_id: UUID,
        event: str,
        credential_version: int,
    ) -> None:
        """Owner-local durable security event atomically with Identity mutation.

        Never emit raw setup tokens, usernames, passwords, auth headers, IPs
        or credential material; Control/Access read projections do not grant.
        """
        if not event.startswith("identity.") or credential_version < 0:
            raise ValueError("identity security event must have a bounded owner revision")
        operation_uuid = uuid4()
        details = AccountSecurityAudit(
            subject_user_id=target_id, credential_version=credential_version
        )
        tx.add(
            OwnerAuditRow(
                operation_uuid=operation_uuid,
                actor_user_id=actor_id,
                project_id=None,
                action=event,
                object_id=str(target_id),
                owner_revision=str(credential_version),
                details=details,
            )
        )
        tx.add(
            OwnerOutboxRow(
                operation_uuid=operation_uuid,
                event_name=event,
                owner_revision=str(credential_version),
                event_payload=details,
            )
        )

    async def issue_first_admin_setup(
        self,
        operator_socket: socket.socket,
    ) -> SecretStr:
        code = await IssueLegacyFirstAdminSetup(
            LegacySetupOperator(self._operator_gate, operator_socket),
            SqlSetupTransactions(self),
            LegacyCredentials(),
            utcnow,
        ).execute()
        return SecretStr(code.value)

    async def issue_registration_invitation(
        self, actor: UserId, *, session: AsyncSession | None = None
    ) -> str:
        return await self._invitations(session).issue_registration(actor)

    async def register(
        self, *, invitation: str, username: str, password: str, session: AsyncSession | None = None
    ) -> User:
        return await RegisterLegacyUser(
            SqlRegistrationTransactions(self, session, utcnow),
            LegacyCredentials(),
            utcnow,
        ).execute(invitation=invitation, username=username, password=password)

    async def authenticate(self, username: str, password: str) -> User | None:
        return await AuthenticateLegacyUser(
            SqlAuthenticationTransactions(self.database, self.repository), LegacyCredentials()
        ).execute(username, password)

    async def authenticate_limited(
        self,
        username: str,
        password: str,
        *,
        source: str,
        pepper: bytes,
    ) -> User | None:
        """Verify legacy credentials with transactional source and identity throttles."""
        return await AuthenticateLimitedLegacyUser(
            SqlLoginTransactions(self.database, self.repository, self._dummy_password_digest),
            LegacyCredentials(),
            utcnow,
        ).execute(username, password, source=source, pepper=pepper)

    async def change_password(
        self,
        actor: UserId,
        *,
        current_password: str,
        new_password: str,
        session: AsyncSession | None = None,
    ) -> None:
        await self._accounts(session).change_password(actor, current_password, new_password)

    async def issue_password_reset(
        self, admin: UserId, target: UserId, *, session: AsyncSession | None = None
    ) -> str:
        return await self._invitations(session).issue_password_reset(admin, target)

    async def reset_password(
        self, token: str, password: str, *, session: AsyncSession | None = None
    ) -> User:
        return await self._accounts(session).reset_password(token, password)

    async def set_superuser(
        self, admin: UserId, target: UserId, enabled: bool, *, session: AsyncSession | None = None
    ) -> User:
        return await self._accounts(session).set_superuser(admin, target, enabled)

    async def set_suspended(
        self, admin: UserId, target: UserId, suspend: bool, *, session: AsyncSession | None = None
    ) -> User:
        return await self._accounts(session).set_suspended(admin, target, suspend)

    async def revoke_invitation(
        self,
        actor: UserId,
        invitation_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        await self._invitations(session).revoke(actor, invitation_id)

    def _accounts(self, session: AsyncSession | None) -> LegacyAccountLifecycle:
        return LegacyAccountLifecycle(
            SqlAccountTransactions(self, session, utcnow), LegacyCredentials(), utcnow
        )

    def _invitations(self, session: AsyncSession | None) -> LegacyIdentityInvitations:
        return LegacyIdentityInvitations(
            SqlInvitationTransactions(self, session),
            LegacyCredentials(),
            LegacyInvitationLinks(self),
            utcnow,
        )
