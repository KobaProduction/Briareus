"""Resources connection SQL custody and atomic audit adapter."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import literal, select, tuple_
from sqlalchemy.exc import IntegrityError

from common.platform_db import PlatformDatabase
from projects._catalog_ledger import OwnerAuditRow
from projects._resource_domain import canonical_alias
from projects._resource_persistence import IntegrationRow
from projects.application.provider_connections import (
    ConnectionCredential,
    ConnectionPage,
    ConnectionSession,
    ConnectionSummary,
    ExistingConnection,
    WriteConnection,
)
from projects.domain.provider_connections import ConnectionFailure, ConnectionRevision
from projects.infrastructure._session_bindings import _CipherSessionBinding
from projects.infrastructure.audit_records import ProviderConnectionAudit
from projects.infrastructure.connection_metadata import StoredConnectionSettings
from projects.infrastructure.integration_settings_jsonb import connection_metadata
from runtime_peer.event_projection import EventPage
from runtime_peer.event_window import EventWindow
from service_runtime.platform_db_mechanics import (
    _DatabaseCipherBinding,
    _PrivateDatabaseBinding,
)


class CredentialEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection: UUID
    project: UUID
    token: str = Field(repr=False)


class ConnectionCursor(BaseModel):
    alias_key: str
    identifier: UUID

    @classmethod
    def parse(cls, raw: str) -> "ConnectionCursor":
        try:
            selected = json.loads(raw)
            if not isinstance(selected, list) or len(selected) != 2:
                raise ValueError
            if not all(isinstance(value, str) for value in selected):
                raise ValueError
            return cls(alias_key=selected[0], identifier=UUID(selected[1]))
        except (ValueError, TypeError):
            raise ConnectionFailure(422, "Invalid connection cursor") from None


def connection_summary(row: IntegrationRow) -> ConnectionSummary:
    configuration = connection_metadata(row.provider_settings).record(
        provider=row.provider,
        auth_type=row.auth_type,
        alias=row.alias,
    )
    return ConnectionSummary(
        id=row.id,
        name=configuration.name,
        alias=row.alias,
        provider=row.provider,
        base_url=configuration.base_url,
        auth_type=row.auth_type,
        credential_configured=True,
        revision=row.version,
        configuration=configuration,
    )


class SqlConnectionTransactions(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ConnectionSession]:
        try:
            async with self._database.transaction() as tx:
                yield SqlConnectionSession(tx, self._cipher)
        except IntegrityError:
            raise ConnectionFailure(409, "Connection name already exists") from None


class SqlConnectionSession(_CipherSessionBinding):
    async def page(self, project_uuid: UUID, cursor: str | None) -> ConnectionPage:
        statement = select(IntegrationRow).where(
            IntegrationRow.owner_project_id == project_uuid,
            IntegrationRow.deleted_at.is_(None),
        )
        if cursor:
            selected = ConnectionCursor.parse(cursor)
            statement = statement.where(
                tuple_(IntegrationRow.alias_key, IntegrationRow.id)
                > tuple_(literal(selected.alias_key), literal(selected.identifier))
            )
        rows = list(
            await self._tx.scalars(
                statement.order_by(IntegrationRow.alias_key, IntegrationRow.id).limit(51)
            )
        )
        last = rows[49] if len(rows) > 50 else None
        return ConnectionPage(
            items=tuple(connection_summary(row) for row in rows[:50]),
            has_more=last is not None,
            next_cursor=json.dumps([last.alias_key, str(last.id)], separators=(",", ":"))
            if last
            else None,
        )

    async def find(
        self,
        identity: ConnectionRevision,
        *,
        lock: bool,
        credential: bool = False,
    ) -> ExistingConnection | None:
        statement = select(IntegrationRow).where(
            IntegrationRow.id == identity.connection_uuid,
            IntegrationRow.owner_project_id == identity.project_uuid,
        )
        row = await self._tx.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            return None
        token = (
            self._credential(row, identity.project_uuid)
            if credential and row.deleted_at is None
            else ""
        )
        return ExistingConnection(
            connection_summary(row), ConnectionCredential(token), row.deleted_at is not None
        )

    def _credential(self, row: IntegrationRow, project_uuid: UUID) -> str:
        try:
            envelope = CredentialEnvelope.model_validate_json(
                self._cipher.decrypt(row.encrypted_credential.encode())
            )
        except (InvalidToken, ValidationError):
            raise ConnectionFailure(503, "Credential binding invalid") from None
        if envelope.connection != row.id or envelope.project != project_uuid:
            raise ConnectionFailure(503, "Credential binding invalid")
        return envelope.token

    async def create(self, command: WriteConnection, now: datetime) -> ConnectionSummary:
        if command.settings is None or command.credential is None:
            raise ConnectionFailure(422, "Invalid connection configuration")
        alias, alias_key = canonical_alias(command.alias)
        row = IntegrationRow(
            id=command.identity.connection_uuid,
            owner_project_id=command.identity.project_uuid,
            alias=alias,
            alias_key=alias_key,
            provider=command.settings.provider,
            auth_type=command.settings.auth_type,
            version=1,
            created_at=now,
            updated_at=now,
            provider_settings=StoredConnectionSettings.from_record(command.settings),
            encrypted_credential="",
        )
        self._apply(row, command)
        self._tx.add(row)
        await self._tx.flush()
        return connection_summary(row)

    async def update(self, command: WriteConnection, now: datetime) -> ConnectionSummary:
        row = await self._row(command.identity)
        self._apply(row, command)
        row.version += 1
        row.updated_at = now
        await self._tx.flush()
        return connection_summary(row)

    def _apply(self, row: IntegrationRow, command: WriteConnection) -> None:
        if command.settings is None or command.credential is None:
            raise ConnectionFailure(422, "Invalid connection configuration")
        row.provider_settings = StoredConnectionSettings.from_record(command.settings)
        row.auth_type = command.settings.auth_type
        envelope = CredentialEnvelope(
            connection=row.id,
            project=command.identity.project_uuid,
            token=command.credential.token,
        )
        row.encrypted_credential = self._cipher.encrypt(
            envelope.model_dump_json().encode()
        ).decode()

    async def _row(self, identity: ConnectionRevision) -> IntegrationRow:
        row = await self._tx.get(IntegrationRow, identity.connection_uuid)
        if row is None or row.owner_project_id != identity.project_uuid:
            raise ConnectionFailure(404, "Connection not found")
        return row

    async def delete(self, identity: ConnectionRevision, now: datetime) -> None:
        row = await self._row(identity)
        row.deleted_at, row.version = now, row.version + 1

    async def audit(self, command: WriteConnection, provider: str, revision: int) -> None:
        self._tx.add(
            OwnerAuditRow(
                operation_uuid=uuid4(),
                actor_user_id=command.actor_uuid,
                project_id=command.identity.project_uuid,
                action="connection." + command.action,
                object_id=str(command.identity.connection_uuid),
                owner_revision=str(revision),
                details=ProviderConnectionAudit(provider=provider),
            )
        )


class SqlConnectionEvents(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(self, project_uuid: UUID, window: EventWindow) -> EventPage:
        statement = select(OwnerAuditRow).where(
            OwnerAuditRow.project_id == project_uuid,
            OwnerAuditRow.action.in_(
                ("connection.create", "connection.update", "connection.delete")
            )
            | OwnerAuditRow.action.like("node.%"),
            OwnerAuditRow.created_at >= window.since,
            OwnerAuditRow.created_at <= window.until,
        )
        if window.after:
            statement = statement.where(
                tuple_(OwnerAuditRow.created_at, OwnerAuditRow.id)
                > tuple_(literal(window.after[0]), literal(window.after[1]))
            )
        async with self._database.transaction() as tx:
            rows = list(
                await tx.scalars(
                    statement.order_by(OwnerAuditRow.created_at, OwnerAuditRow.id).limit(129)
                )
            )
        return window.result(rows)
