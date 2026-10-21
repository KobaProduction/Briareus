"""Project-scoped human connection management, owned by Resources.

Credentials are write-only, encrypted in the existing Catalog database. Current
Platform membership is independently checked on every command. This is not an
AgentSession grant or the external MCP execution plane.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError

from common.owner_runtime import VerifiedOwnerIngress, create_owner_app
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from common.platform_errors import InvalidInput
from projects._catalog_ledger import OwnerAuditRow
from projects._connection_probe import check_connection
from projects.connection_forms import CONNECTION_FORM, validate_connection
from projects._resource_domain import canonical_alias
from projects._resource_persistence import IntegrationRow
from runtime_peer import PeerClient, PeerIdentity, PeerVerifier
from runtime_peer.server import SignedOwnerApp, serve_unix


class ConnectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID
    actor_uuid: UUID
    identity_expires_at: datetime
    action: Literal["forms", "list", "verify", "create", "update", "delete", "check", "events.read"]
    event_window: dict[str, object] = Field(default_factory=dict, max_length=3)
    connection_uuid: UUID | None = None
    alias: str = Field(default="", max_length=128)
    credential: SecretStr = Field(default=SecretStr(""))
    configuration: dict[str, object] = Field(default_factory=dict, max_length=12)
    expected_revision: int | None = Field(default=None, strict=True, ge=1)
    cursor: str | None = Field(default=None, max_length=1024)


class Ingress:
    async def verify_running_ingress(self) -> VerifiedOwnerIngress:
        info = os.stat(os.environ["RESOURCES_RUNTIME_SOCKET"])
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 7:
            raise ValueError("Private Resources listener required")
        return VerifiedOwnerIngress("resources", "unix-peer", True,
                                    datetime.now(UTC) + timedelta(seconds=10))


def create_app(platform: PeerClient, cipher: Fernet):
    app = create_owner_app("resources", trusted_ingress=Ingress())
    owner_lifespan = app.router.lifespan_context
    database = None
    from projects.node_management import node_router
    nodes=node_router(platform=platform, resolve_database=lambda: database, cipher=cipher)
    app.include_router(nodes)

    @asynccontextmanager
    async def lifespan(current):
        nonlocal database
        async with owner_lifespan(current):
            database = PlatformDatabase(OwnerDatabaseSettings(owner="resources"))
            try:
                yield
            finally:
                await nodes.node_placements.close()
                await database.close()
                database = None
                await platform.close()
                from projects.node_control import NodeControl
                if NodeControl.from_environment.cache_info().currsize:
                    await NodeControl.from_environment().close()
    app.router.lifespan_context = lifespan

    async def authorize(command: ConnectionCommand):
        now = datetime.now(UTC)
        if (command.project_uuid.version != 4 or command.actor_uuid.version != 4
            or command.identity_expires_at.tzinfo is None
            or not now < command.identity_expires_at <= now + timedelta(seconds=30)):
            raise HTTPException(403, "Current project identity required")
        status, actor = await platform.call("/internal/v1/platform/oidc/actor-context", {
            "issuer": command.issuer, "subject": command.subject,
            "project_uuid": str(command.project_uuid),
        })
        if status != 200:
            raise HTTPException(403 if status == 403 else 503, "Current Platform source unavailable")
        expiry = datetime.fromisoformat(actor["expires_at"])
        if (actor.get("issuer") != command.issuer or actor.get("subject") != command.subject
            or actor.get("actor_uuid") != str(command.actor_uuid)
            or actor.get("project_uuid") != str(command.project_uuid)
            or "use_resources" not in actor.get("permissions", [])
            or expiry.tzinfo is None or not now < expiry <= now + timedelta(seconds=30)):
            raise HTTPException(403, "Current project membership required")
        # Connection management can expose a provider's identity and changes
        # credential custody. Ordinary project members cannot manage secrets.
        if actor.get("role") != "operator":
            raise HTTPException(403, "Platform operator required")
        return min(expiry, command.identity_expires_at)

    def summary(row):
        configuration = {key: row.provider_settings[key] for key in (
            "name", "provider", "auth_type", "base_url", "external_id", "ca_cert_pem", "git_policy"
        ) if key in row.provider_settings}
        configuration.update(name=row.provider_settings.get("display_name") or row.alias,
                             provider=row.provider, auth_type=row.auth_type)
        return {"id": str(row.id), "name": configuration["name"], "alias": row.alias,
                "provider": row.provider, "base_url": configuration.get("base_url", ""),
                "auth_type": row.auth_type, "credential_configured": True,
                "revision": row.version, "configuration": configuration}

    @app.post("/internal/v1/resources/connections", include_in_schema=False)
    async def connections(command: ConnectionCommand, request: Request):
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            raise HTTPException(403, "Human management peer required")
        try:
            expiry = await authorize(command)
            if command.action == "events.read":
                from runtime_peer.event_window import EventWindow
                window = EventWindow.parse(command.event_window)
                statement = select(OwnerAuditRow).where(OwnerAuditRow.project_id == command.project_uuid,
                    (OwnerAuditRow.action.in_(("connection.create", "connection.update", "connection.delete"))
                     | OwnerAuditRow.action.like("node.%")),
                    OwnerAuditRow.created_at >= window.since, OwnerAuditRow.created_at <= window.until)
                if window.after:
                    statement = statement.where(tuple_(OwnerAuditRow.created_at, OwnerAuditRow.id) > tuple_(*window.after))
                async with database.transaction() as tx:
                    rows = list(await tx.scalars(statement.order_by(OwnerAuditRow.created_at, OwnerAuditRow.id).limit(129)))
                if expiry <= datetime.now(UTC):
                    raise HTTPException(403, "Current Platform proof expired")
                return JSONResponse(window.result(rows))
            if command.action == "forms":
                return JSONResponse(CONNECTION_FORM.json_schema())
            form = None
            if command.action in {"create", "verify", "update"}:
                credential = command.credential
                if command.action == "update" and (command.connection_uuid is None or command.expected_revision is None):
                    raise HTTPException(422, "Existing connection revision required")
                if command.connection_uuid is not None and command.action != "create" and command.expected_revision is not None:
                    async with database.transaction() as tx:
                        existing = await tx.scalar(select(IntegrationRow).where(
                            IntegrationRow.id == command.connection_uuid,
                            IntegrationRow.owner_project_id == command.project_uuid,
                            IntegrationRow.deleted_at.is_(None)))
                        if existing is None:
                            raise HTTPException(404, "Connection not found")
                        if existing.version != command.expected_revision:
                            raise HTTPException(409, "Connection changed; reload before editing")
                        if command.configuration.get("provider") != existing.provider:
                            raise HTTPException(422, "Provider cannot change on an existing connection")
                        if not credential.get_secret_value():
                            envelope = json.loads(cipher.decrypt(existing.encrypted_credential.encode()))
                            if envelope["connection"] != str(existing.id) or envelope["project"] != str(command.project_uuid):
                                raise HTTPException(503, "Credential binding invalid")
                            credential = SecretStr(envelope["token"])
                form = validate_connection({**command.configuration, "credential": credential})
                options = form.model_dump(mode="json", exclude={"credential"})
                probe_args = (form.provider, form.base_url, form.credential.get_secret_value(),
                              form.auth_type, options.get("external_id", ""), form.ca_cert_pem)
                try:
                    async with asyncio.timeout(7):
                        checked = await asyncio.to_thread(check_connection, *probe_args)
                except Exception:
                    checked = {"status": "unavailable", "message": "Провайдер не подтвердил подключение"}
                if command.action == "verify":
                    await authorize(command)
                    return JSONResponse(checked)
                if checked.get("status") != "connected":
                    return JSONResponse({"error": {"code": "CONNECTION_VERIFICATION_REQUIRED"}}, status_code=422)
                expiry = await authorize(command)
            async with database.transaction() as tx:
                if command.action == "list":
                    statement=select(IntegrationRow).where(IntegrationRow.owner_project_id == command.project_uuid,
                        IntegrationRow.deleted_at.is_(None))
                    if command.cursor:
                        try:
                            selected=json.loads(command.cursor)
                            if not isinstance(selected,list) or len(selected)!=2 or any(not isinstance(v,str) for v in selected):raise ValueError
                            alias_key, identifier=selected
                            identifier=UUID(identifier)
                            if not isinstance(alias_key,str):raise ValueError
                        except (ValueError,TypeError):raise HTTPException(422,"Invalid connection cursor") from None
                        statement=statement.where(tuple_(IntegrationRow.alias_key,IntegrationRow.id)>tuple_(alias_key,identifier))
                    rows=list(await tx.scalars(statement.order_by(IntegrationRow.alias_key,IntegrationRow.id).limit(51)))
                    last=rows[49] if len(rows)>50 else None
                    result={"items":[summary(row) for row in rows[:50]],"has_more":last is not None,
                        "next_cursor":json.dumps([last.alias_key,str(last.id)],separators=(',',':')) if last else None}
                else:
                    if command.connection_uuid is None or command.connection_uuid.version != 4:
                        raise HTTPException(422, "Connection UUID required")
                    row = await tx.scalar(select(IntegrationRow).where(
                        IntegrationRow.id == command.connection_uuid,
                        IntegrationRow.owner_project_id == command.project_uuid,
                    ).with_for_update())
                    if command.action == "create":
                        if row is not None:
                            raise HTTPException(409, "Connection already exists; refresh the list")
                        alias, alias_key = canonical_alias(command.alias)
                        provider, auth_type = form.provider, form.auth_type
                        token = form.credential.get_secret_value()
                        settings = {**options, "display_name": form.name}
                        envelope = {"connection": str(command.connection_uuid), "project": str(command.project_uuid), "token": token}
                        row = IntegrationRow(id=command.connection_uuid, owner_project_id=command.project_uuid,
                            alias=alias, alias_key=alias_key, provider=provider, auth_type=auth_type,
                            provider_settings=settings, encrypted_credential=cipher.encrypt(json.dumps(envelope).encode()).decode())
                        tx.add(row)
                        result = {"item": summary(row)}
                    elif row is None or row.deleted_at is not None:
                        raise HTTPException(404, "Connection not found")
                    elif command.action == "update":
                        if row.version != command.expected_revision:
                            raise HTTPException(409, "Connection changed; reload before editing")
                        row.provider_settings = {**options, "display_name": form.name}
                        row.auth_type = form.auth_type
                        envelope = {"connection": str(row.id), "project": str(command.project_uuid),
                                    "token": form.credential.get_secret_value()}
                        row.encrypted_credential = cipher.encrypt(json.dumps(envelope).encode()).decode()
                        row.version += 1
                        row.updated_at = datetime.now(UTC)
                        result = {"item": summary(row)}
                    elif command.action == "delete":
                        if row.version != command.expected_revision:
                            raise HTTPException(409, "Connection changed; reload before deleting")
                        row.deleted_at = datetime.now(UTC)
                        row.version += 1
                        result = {"deleted": True}
                    else:
                        envelope = json.loads(cipher.decrypt(row.encrypted_credential.encode()))
                        if envelope["connection"] != str(row.id) or envelope["project"] != str(command.project_uuid):
                            raise HTTPException(503, "Credential binding invalid")
                        # No provider call while holding a database lock/transaction.
                        probe = (row.provider, row.provider_settings["base_url"], envelope["token"],
                                 row.auth_type, row.provider_settings.get("external_id", ""),
                                 row.provider_settings.get("ca_cert_pem", ""))
                        result = None
                    if command.action in {"create", "update", "delete"}:
                        if expiry <= datetime.now(UTC):
                            raise HTTPException(403, "Current Platform proof expired")
                        tx.add(OwnerAuditRow(operation_uuid=uuid4(), actor_user_id=command.actor_uuid,
                            project_id=command.project_uuid, action="connection." + command.action,
                            object_id=str(row.id), owner_revision=str(row.version or 1), details={"provider": row.provider}))
            if result is None:
                try:
                    async with asyncio.timeout(7):
                        result = await asyncio.to_thread(check_connection, *probe)
                except Exception:
                    result = {"status": "unavailable", "message": "Не удалось проверить подключение; проверьте адрес и доступность провайдера"}
                await authorize(command)
            if expiry <= datetime.now(UTC):
                raise HTTPException(403, "Current Platform proof expired")
            return JSONResponse(result)
        except (InvalidInput, ValueError):
            raise HTTPException(422, "Invalid connection configuration") from None
        except IntegrityError:
            raise HTTPException(409, "Connection name already exists") from None

    return app


def main():
    signing_key = os.environ["RESOURCES_SIGNING_KEY_FILE"]
    platform = PeerClient(name="briareus:resources", signing_key_file=signing_key,
        socket_path=os.environ["PLATFORM_PANEL_SOCKET"],
        owner=PeerIdentity.from_file("briareus:platform", 1000, os.environ["PLATFORM_RUNTIME_VERIFY_KEY_FILE"]))
    cipher = Fernet(Path(os.environ["RESOURCES_ENCRYPTION_KEY_FILE"]).read_bytes().strip())
    app = create_app(platform, cipher)
    callers = [
        PeerIdentity.from_file("briareus:control-panel-api", 1001, os.environ["RESOURCES_PANEL_VERIFY_KEY_FILE"]),
    ]
    if os.environ.get("RESOURCES_GATEWAY_VERIFY_KEY_FILE"):
        callers.append(PeerIdentity.from_file("briareus:gateway", 1000,
                                             os.environ["RESOURCES_GATEWAY_VERIFY_KEY_FILE"]))
    if os.environ.get("RESOURCES_ACCESS_VERIFY_KEY_FILE"):
        callers.append(PeerIdentity.from_file("briareus:authorization",1002,
                                             os.environ["RESOURCES_ACCESS_VERIFY_KEY_FILE"]))
    signed = SignedOwnerApp(app, verifier=PeerVerifier("briareus:resources", tuple(callers)),
                            signing_key_file=signing_key)
    serve_unix(signed, os.environ["RESOURCES_RUNTIME_SOCKET"], diagnostics_port=8000)


if __name__ == "__main__":
    main()
