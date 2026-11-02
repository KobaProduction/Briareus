"""Private Team/Project reusable configuration selection (metadata only).

`all` yields the effective authorized collection, including duplicate names
with explicit origin. Even active Team members cannot export raw secrets by
using this selector; credential/value injection is a separate C1-B transport.
"""

from __future__ import annotations

import asyncio
import math
from typing import Protocol
from uuid import UUID

from project_runtime_client.domain.authorization import (
    ProjectInvocation,
    ProjectPermit,
)
from project_runtime_client.domain.resource_query import (
    ResourceFilter,
    ResourceQuery,
    ResourceSelectionError,
    effective_collection,
    one_named_resource,
)
from project_runtime_client.domain.resources import (
    ProjectVariableError,
    ProjectVariableRef,
)
from project_runtime_client.domain.revisions import valid_project_revision

from .resource_authority import ResourceAuthorityPort


class ProjectVariablePort(Protocol):
    async def resolve_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        variable_id: UUID,
        permit: ProjectPermit,
    ) -> ProjectVariableRef: ...

    async def list_effective_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
    ) -> tuple[ProjectVariableRef, ...]: ...


class ProjectVariableSelector:
    def __init__(
        self,
        authority: ResourceAuthorityPort,
        resolver: ProjectVariablePort | None = None,
        *,
        operation_timeout_seconds: float = 15.0,
    ) -> None:
        if not math.isfinite(operation_timeout_seconds) or not 0 < operation_timeout_seconds <= 300:
            raise ValueError("Project variable timeout must be finite and positive")
        self.authority = authority
        self._resolver = resolver
        self._operation_timeout_seconds = operation_timeout_seconds

    @staticmethod
    def _validate(
        record: ProjectVariableRef, *, permit: ProjectPermit, variable_id: UUID | None = None
    ) -> None:
        if not isinstance(record, ProjectVariableRef):
            raise ProjectVariableError("PROJECT_VARIABLE_ACCESS_DENIED")
        record.require_access(
            project_uuid=permit.project_id,
            access_revision=permit.project_access_revision,
            variable_uuid=variable_id,
        )

    async def list_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> tuple[ProjectVariableRef, ...]:
        query = ResourceQuery(scope, owner_id)
        permit = await self.authority.require(invocation, "resources.use")
        revision = permit.project_access_revision
        if not isinstance(revision, str) or not valid_project_revision(revision):
            raise ProjectVariableError("PROJECT_RESOURCE_FENCE_UNAVAILABLE")
        if self._resolver is None:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                records = await self._resolver.list_effective_metadata(invocation, permit=permit)
            if not isinstance(records, tuple):
                raise ProjectVariableError("PROJECT_VARIABLE_RESPONSE_INVALID")
            for record in records:
                self._validate(record, permit=permit)
            return effective_collection(
                records,
                project_id=permit.project_id,
                access_revision=revision,
                query=query,
            )
        except (ProjectVariableError, ResourceSelectionError):
            raise
        except Exception as exc:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE") from exc

    async def select_metadata(
        self, invocation: ProjectInvocation, *, variable_id: UUID
    ) -> ProjectVariableRef:
        if not isinstance(variable_id, UUID):
            raise ProjectVariableError("PROJECT_VARIABLE_ID_INVALID")
        permit = await self.authority.require(invocation, "resources.use")
        if self._resolver is None:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                record = await self._resolver.resolve_metadata(
                    invocation, variable_id=variable_id, permit=permit
                )
        except ProjectVariableError:
            raise
        except Exception as exc:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE") from exc
        self._validate(record, permit=permit, variable_id=variable_id)
        return record

    async def select_by_name(
        self,
        invocation: ProjectInvocation,
        *,
        name: str,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> ProjectVariableRef:
        records = await self.list_metadata(invocation, scope=scope, owner_id=owner_id)
        try:
            return one_named_resource(records, name=name)
        except ResourceSelectionError as exc:
            raise ProjectVariableError(exc.code) from exc
