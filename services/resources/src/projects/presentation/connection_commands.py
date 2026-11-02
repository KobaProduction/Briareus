"""Existing human connection wire contract and thin use-case adaptation."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from common.platform_errors import InvalidInput
from projects.application.provider_connections import (
    AuthorizeConnections,
    CheckExistingConnection,
    ConnectionCredential,
    ConnectionEvents,
    ManageConnections,
    PreparedConnectionWrite,
    VerificationRequired,
    VerifyAndSaveConnection,
    VerifyProviderConnection,
    WriteConnection,
)
from projects.connection_forms import (
    CONNECTION_FORM,
    ConnectionForm,
    connection_settings,
    validate_connection,
)
from projects.domain.node_administration import OperatorSelector
from projects.domain.provider_connections import (
    ConnectionFailure,
    ConnectionRevision,
    ProviderCheck,
    require_connection_proof,
)
from runtime_peer.connection_contracts import ConnectionConfigurationInput, _configuration_input
from runtime_peer.connection_form_schema import ConnectionSchema
from runtime_peer.event_window_wire import EventWindowRequest


class ConnectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID
    actor_uuid: UUID
    identity_expires_at: datetime
    action: Literal["forms", "list", "verify", "create", "update", "delete", "check", "events.read"]
    event_window: EventWindowRequest | None = None
    connection_uuid: UUID | None = None
    alias: str = Field(default="", max_length=128)
    credential: SecretStr = Field(default=SecretStr(""))
    configuration: ConnectionConfigurationInput | None = None
    expected_revision: int | None = Field(default=None, strict=True, ge=1)
    cursor: str | None = Field(default=None, max_length=1024)

    configuration_input = field_validator("configuration", mode="before")(
        staticmethod(_configuration_input)
    )

    @field_validator("event_window", mode="before")
    @classmethod
    def event_window_input(cls, value: object) -> EventWindowRequest | None:
        if value == {}:
            return None
        if value is None:
            raise ValueError("Event window must be an object")
        return EventWindowRequest.model_validate(value)

    def selector(self) -> OperatorSelector:
        return OperatorSelector(
            self.issuer, self.subject, self.actor_uuid, self.project_uuid, self.identity_expires_at
        )

    def revision(self) -> ConnectionRevision:
        if self.connection_uuid is None:
            raise ConnectionFailure(422, "Connection UUID required")
        return ConnectionRevision(self.project_uuid, self.connection_uuid, self.expected_revision)


class ProviderCheckPayload(BaseModel):
    status: Literal["connected", "denied", "unavailable"]
    message: str | None = None
    identity: str | None = None

    @classmethod
    def from_record(cls, result: ProviderCheck) -> "ProviderCheckPayload":
        if result.status == "connected":
            return cls(status=result.status, identity=result.identity)
        return cls(status=result.status, message=result.message)


class ConnectionBoundary:
    def __init__(
        self,
        authority: AuthorizeConnections,
        connections: ManageConnections,
        verifier: VerifyProviderConnection,
        events: ConnectionEvents,
        now: Callable[[], datetime],
    ) -> None:
        self._authority, self._connections, self._verifier = authority, connections, verifier
        self._events, self._now = events, now

    async def execute(self, command: ConnectionCommand, request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            raise HTTPException(403, "Human management peer required")
        try:
            expiry = await self._authority.execute(command.selector())
            return await self._dispatch(command, expiry)
        except ConnectionFailure as exc:
            raise HTTPException(exc.status, exc.detail) from None
        except (InvalidInput, ValueError):
            raise HTTPException(422, "Invalid connection configuration") from None

    async def _dispatch(self, command: ConnectionCommand, expiry: datetime) -> JSONResponse:
        if command.action == "forms":
            schema = ConnectionSchema.model_validate(CONNECTION_FORM.json_schema())
            return JSONResponse(schema.model_dump(mode="json", by_alias=True, exclude_unset=True))
        if command.action == "events.read":
            if command.event_window is None:
                raise ValueError("Exact event window required")
            events = await self._events.read(command.project_uuid, command.event_window.window())
            require_connection_proof(expiry, self._now())
            return JSONResponse(asdict(events))
        if command.action == "list":
            page = await self._connections.page(command.project_uuid, command.cursor, expiry)
            return JSONResponse(
                page.model_dump(mode="json", exclude_none=True, exclude_unset=True)
                | {"next_cursor": page.next_cursor}
            )
        if command.action == "check":
            return await self._check(command, expiry)
        if command.action == "delete":
            result = await self._connections.write(
                WriteConnection(
                    "delete",
                    command.revision(),
                    command.actor_uuid,
                    command.alias,
                    None,
                    None,
                ),
                expiry,
            )
            return JSONResponse(result.model_dump(mode="json"))
        return await self._verified_write(command, expiry)

    async def _form(self, command: ConnectionCommand, expiry: datetime) -> ConnectionForm:
        credential = command.credential
        if command.configuration is None:
            raise ConnectionFailure(422, "Invalid connection configuration")
        if command.action == "update" and (
            command.connection_uuid is None or command.expected_revision is None
        ):
            raise ConnectionFailure(422, "Existing connection revision required")
        if (
            command.connection_uuid is not None
            and command.action != "create"
            and command.expected_revision is not None
        ):
            existing = await self._connections.existing(
                command.revision(),
                expiry,
                credential=not credential.get_secret_value(),
            )
            command.revision().require_matches(existing.summary.revision)
            if command.configuration.provider != existing.summary.provider:
                raise ConnectionFailure(422, "Provider cannot change on an existing connection")
            if not credential.get_secret_value():
                credential = SecretStr(existing.credential.token)
        return validate_connection(command.configuration, credential)

    async def _verified_write(self, command: ConnectionCommand, expiry: datetime) -> JSONResponse:
        form = await self._form(command, expiry)
        settings = connection_settings(form)
        if command.action not in {"verify", "create", "update"}:
            raise ConnectionFailure(422, "Invalid connection action")
        result = await VerifyAndSaveConnection(
            self._authority,
            self._connections,
            self._verifier,
        ).execute(
            PreparedConnectionWrite(
                command.action,
                command.selector(),
                command.connection_uuid,
                command.expected_revision,
                command.alias,
                settings,
                ConnectionCredential(form.credential.get_secret_value()),
            )
        )
        if isinstance(result, ProviderCheck):
            return JSONResponse(
                ProviderCheckPayload.from_record(result).model_dump(mode="json", exclude_unset=True)
            )
        if isinstance(result, VerificationRequired):
            return JSONResponse(
                {"error": {"code": "CONNECTION_VERIFICATION_REQUIRED"}}, status_code=422
            )
        return JSONResponse(result.model_dump(mode="json", exclude_none=True, exclude_unset=True))

    async def _check(self, command: ConnectionCommand, expiry: datetime) -> JSONResponse:
        checked = await CheckExistingConnection(
            self._authority,
            self._connections,
            self._verifier,
            self._now,
        ).execute(command.selector(), command.revision(), expiry)
        return JSONResponse(
            ProviderCheckPayload.from_record(checked).model_dump(mode="json", exclude_unset=True)
        )


connection_now = partial(datetime.now, UTC)
