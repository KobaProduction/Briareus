"""Private Team/Project provider selector, without credential material.

`scope=all` is a collection, never an implicit single-resource choice.
The backend is authoritative for caller, membership, live revisions and
owner-specific permission checks; no public interface is mounted here.
"""

from __future__ import annotations

import asyncio
import math
from typing import Protocol
from uuid import UUID

from project_runtime_client.domain.authorization import (
    ProjectAction,
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
    IntegrationOperation,
    IntegrationProvider,
    ProjectIntegrationError,
    ProjectIntegrationRef,
    integration_action,
)
from project_runtime_client.domain.revisions import valid_project_revision

from .resource_authority import ResourceAuthorityPort


class ProjectIntegrationPort(Protocol):
    async def resolve(
        self,
        invocation: ProjectInvocation,
        *,
        integration_id: UUID,
        provider: IntegrationProvider,
        permit: ProjectPermit,
    ) -> ProjectIntegrationRef: ...

    async def list_effective(
        self,
        invocation: ProjectInvocation,
        *,
        provider: IntegrationProvider,
        permit: ProjectPermit,
    ) -> tuple[ProjectIntegrationRef, ...]: ...


class ProjectIntegrationSelector:
    """Use/read external provider capability, not management of secret records.

    All active Team members MAY manage shared integrations in the accepted MVP;
    that separate Team-authorized mutation port is backend-owned C1-B. This
    selector never restricts use to a Team owner or exports credentials.
    """

    def __init__(
        self,
        authority: ResourceAuthorityPort,
        resolver: ProjectIntegrationPort | None = None,
        *,
        operation_timeout_seconds: float = 15.0,
    ) -> None:
        if not math.isfinite(operation_timeout_seconds) or not 0 < operation_timeout_seconds <= 300:
            raise ValueError("Project resource timeout must be finite and positive")
        self.authority = authority
        self._resolver = resolver
        self._operation_timeout_seconds = operation_timeout_seconds

    @staticmethod
    def _action(provider: IntegrationProvider, operation: IntegrationOperation) -> ProjectAction:
        return integration_action(provider, operation)

    @staticmethod
    def _validate(
        record: ProjectIntegrationRef,
        *,
        permit: ProjectPermit,
        provider: IntegrationProvider,
        operation: IntegrationOperation,
        integration_id: UUID | None = None,
    ) -> None:
        if not isinstance(record, ProjectIntegrationRef):
            raise ProjectIntegrationError("PROJECT_INTEGRATION_ACCESS_DENIED")
        record.require_access(
            project_uuid=permit.project_id,
            access_revision=permit.project_access_revision,
            provider=provider,
            operation=operation,
            integration_uuid=integration_id,
        )

    async def _effective(
        self,
        invocation: ProjectInvocation,
        *,
        provider: IntegrationProvider,
        permit: ProjectPermit,
        query: ResourceQuery,
    ) -> tuple[ProjectIntegrationRef, ...]:
        revision = permit.project_access_revision
        if not isinstance(revision, str) or not valid_project_revision(revision):
            raise ProjectIntegrationError("PROJECT_RESOURCE_FENCE_UNAVAILABLE")
        if self._resolver is None:
            raise ProjectIntegrationError("PROJECT_INTEGRATION_RESOLVER_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                raw = await self._resolver.list_effective(
                    invocation, provider=provider, permit=permit
                )
            if not isinstance(raw, tuple):
                raise ProjectIntegrationError("PROJECT_INTEGRATION_RESPONSE_INVALID")
            # Validate *all* supplied records before filtering; a forged/stale
            # hidden record is not ignored or allowed to make a partial result.
            for record in raw:
                if not isinstance(record, ProjectIntegrationRef):
                    raise ProjectIntegrationError("PROJECT_INTEGRATION_ACCESS_DENIED")
                if record.provider != provider:
                    raise ProjectIntegrationError("PROJECT_INTEGRATION_ACCESS_DENIED")
                record.scope.verify_for(permit.project_id)
                if record.scope.project_access_revision != permit.project_access_revision:
                    raise ProjectIntegrationError("PROJECT_INTEGRATION_ACCESS_STALE")
            return effective_collection(
                raw,
                project_id=permit.project_id,
                access_revision=revision,
                query=query,
            )
        except (ProjectIntegrationError, ResourceSelectionError):
            raise
        except Exception as exc:
            raise ProjectIntegrationError("PROJECT_INTEGRATION_RESOLVER_UNAVAILABLE") from exc

    async def list(
        self,
        invocation: ProjectInvocation,
        *,
        provider: IntegrationProvider,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> tuple[ProjectIntegrationRef, ...]:
        query = ResourceQuery(scope, owner_id)
        permit = await self.authority.require(invocation, self._action(provider, "read"))
        return await self._effective(invocation, provider=provider, permit=permit, query=query)

    async def select(
        self,
        invocation: ProjectInvocation,
        *,
        integration_id: UUID,
        provider: IntegrationProvider,
        operation: IntegrationOperation = "read",
    ) -> ProjectIntegrationRef:
        if not isinstance(integration_id, UUID):
            raise ProjectIntegrationError("PROJECT_INTEGRATION_ID_INVALID")
        permit = await self.authority.require(invocation, self._action(provider, operation))
        if self._resolver is None:
            raise ProjectIntegrationError("PROJECT_INTEGRATION_RESOLVER_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                record = await self._resolver.resolve(
                    invocation,
                    integration_id=integration_id,
                    provider=provider,
                    permit=permit,
                )
        except ProjectIntegrationError:
            raise
        except Exception as exc:
            raise ProjectIntegrationError("PROJECT_INTEGRATION_RESOLVER_UNAVAILABLE") from exc
        self._validate(
            record,
            permit=permit,
            provider=provider,
            operation=operation,
            integration_id=integration_id,
        )
        return record

    async def select_by_name(
        self,
        invocation: ProjectInvocation,
        *,
        name: str,
        provider: IntegrationProvider,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
        operation: IntegrationOperation = "read",
    ) -> ProjectIntegrationRef:
        query = ResourceQuery(scope, owner_id)
        permit = await self.authority.require(invocation, self._action(provider, operation))
        records = await self._effective(invocation, provider=provider, permit=permit, query=query)
        try:
            # Duplicate Team + Project aliases deliberately stay ambiguous.
            selected = one_named_resource(records, name=name)
        except ResourceSelectionError as exc:
            raise ProjectIntegrationError(exc.code) from exc
        self._validate(selected, permit=permit, provider=provider, operation=operation)
        return selected
