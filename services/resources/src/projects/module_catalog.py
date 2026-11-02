"""Panel peer adapter/composition for the typed Resources module catalog."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.platform_db import PlatformDatabase
from node_protocol.catalog import ARTIFACTS, LOGICAL_MODULES
from projects.application.module_catalog import (
    CatalogSnapshot,
    PublishModuleRelease,
    ReadModuleCatalog,
)
from projects.domain.module_catalog import (
    ArtifactDefinition,
    CatalogError,
    LogicalModule,
    Publication,
    PublicationIdentity,
    ReleaseSummary,
    ResourceLimits,
)
from projects.infrastructure.catalog_records import (
    InputPayload,
    approved_registries,
    artifact_definition,
)
from projects.infrastructure.module_catalog import SqlCatalogTransactions

if TYPE_CHECKING:
    from projects.presentation.node_commands import NodeCommand


class ArtifactPayload(BaseModel):
    key: str
    name: str
    node_adapter: bool
    lifecycle: str
    workspace: bool
    inputs: InputPayload
    minimum_limits: ResourceLimits
    default_limits: ResourceLimits

    @classmethod
    def from_definition(cls, definition: ArtifactDefinition) -> ArtifactPayload:
        return cls(
            key=definition.key,
            name=definition.name,
            node_adapter=definition.node_adapter,
            lifecycle=definition.lifecycle,
            workspace=definition.workspace,
            inputs=InputPayload.from_record(definition.inputs),
            minimum_limits=definition.minimum_limits,
            default_limits=definition.default_limits,
        )


class CatalogPayload(BaseModel):
    modules: tuple[LogicalModule, ...]
    artifacts: tuple[ArtifactPayload, ...]
    releases: tuple[ReleaseSummary, ...]

    @classmethod
    def from_snapshot(cls, snapshot: CatalogSnapshot) -> CatalogPayload:
        return cls(
            modules=snapshot.modules,
            releases=snapshot.releases,
            artifacts=tuple(ArtifactPayload.from_definition(item) for item in snapshot.artifacts),
        )


def catalog_error(error: CatalogError) -> HTTPException:
    detail = str(error)
    if detail in ("Current Platform proof required", "Current publication authority required"):
        return HTTPException(403, detail)
    if detail in (
        "Unknown deployable module",
        "Image registry not approved for publication",
        "Invalid publication",
    ):
        return HTTPException(422, detail)
    return HTTPException(409, detail)


async def catalog_command(
    command: NodeCommand, *, database: PlatformDatabase, cipher: Fernet, expiry: datetime
) -> JSONResponse:
    data = command.module
    if data is None:
        raise HTTPException(422, "Module command required")
    transactions = SqlCatalogTransactions(database, cipher)

    now = partial(datetime.now, UTC)

    try:
        if data.action == "catalog":
            definitions = tuple(artifact_definition(item) for item in ARTIFACTS.values())
            modules = tuple(
                LogicalModule(item.key, item.name, item.components) for item in LOGICAL_MODULES
            )
            snapshot = await ReadModuleCatalog(transactions, now).execute(
                definitions, modules, expiry
            )
            return JSONResponse(
                jsonable_encoder(CatalogPayload.from_snapshot(snapshot), exclude_none=True)
            )
        if data.publication is None:
            raise HTTPException(422, "Publication required")
        value = data.publication
        source = ARTIFACTS.get(value.module)
        if source is None:
            raise CatalogError("Unknown deployable module")
        digest = hashlib.sha256(
            json.dumps(
                command.model_dump(mode="json", exclude={"identity_expires_at"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        identity = PublicationIdentity(
            command.operation_uuid, command.actor_uuid, command.project_uuid, digest
        )
        publication = Publication(
            value.id,
            value.module,
            value.source_commit,
            value.input_fingerprint,
            value.image,
            value.platform,
        )
        result = await PublishModuleRelease(transactions, now).execute(
            identity,
            publication,
            artifact_definition(source),
            approved_registries(os.environ.get("RESOURCES_RELEASE_REGISTRIES", "[]")),
            expiry,
        )
        return JSONResponse(asdict(result))
    except CatalogError as exc:
        raise catalog_error(exc) from exc
