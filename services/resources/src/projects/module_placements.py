"""Durable project placement intent and signed gRPC reconciliation, without DB locks across I/O."""

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from node_protocol import Deployment, ResourceLimits, WorkspaceMount
from node_protocol.diagnostics import FailureDiagnostic, diagnostic_payload
from node_protocol.domain.observations import NodeOperation, NodeReply
from node_protocol.management import PlacementInput
from projects._node_persistence import (
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    ProjectModuleBindingRow,
)
from projects.application.node_control import NodeExecutionControl
from projects.application.placement_execution import PlacementCreationIntent, ReconcilePlacement
from projects.application.placement_listing import ReadProjectPlacements
from projects.application.placement_reconciliation import reconcile_receipt
from projects.application.placement_recovery import RecoverPlacement
from projects.application.placement_update import UpdatePlacement
from projects.domain.module_catalog import CatalogError
from projects.domain.module_catalog import ResourceLimits as ProfileLimits
from projects.domain.node_administration import (
    NodeActor,
    NodeConflict,
    NodeForbidden,
    NodeInvalid,
    NodeMissing,
    OperatorAuthority,
)
from projects.domain.placement_reconciliation import OperationReceipt, OperationState
from projects.domain.placement_recovery import PlacementReconciliationBusy, RecoveryIntent
from projects.domain.placement_update import UpdateIntent
from projects.infrastructure.placement_audit import audit_placement
from projects.infrastructure.placement_creation import create_placement_intent
from projects.infrastructure.placement_execution import approved_restoration, execution_target
from projects.infrastructure.placement_listing import SqlPlacementReader, operation_view
from projects.infrastructure.placement_listing import operation_diagnostic as operation_diagnostic
from projects.infrastructure.placement_nodes import qualified_placement_node
from projects.infrastructure.placement_recovery import SqlPlacementRecoveryTransactions
from projects.infrastructure.placement_releases import approved_placement_release
from projects.infrastructure.placement_storage import (
    ensure_project_storage,
    require_project_workspace,
)
from projects.infrastructure.placement_update import SqlPlacementUpdateTransactions
from projects.node_control import NodeControl
from projects.presentation.node_commands import NodeCommand
from projects.presentation.placement_listing import placement_list_response
from projects.presentation.placement_operation import (
    PlacementOperationSummary,
    placement_operation_response,
    require_placement_capacity,
)

ACTIVE = {"queued", "pulling", "stopping", "creating", "checking", "rolling_back"}
ERRORS = {"UPDATE_FAILED", "ROLLBACK_FAILED", "CONTROLLER_INTERRUPTED", "UNMANAGED_INSTANCE"}


def _placement_node(
    row: NodeRow | None,
    actor: NodeActor,
    *,
    scope_detail: str = "Node must belong to the current project scope",
) -> NodeRow:
    try:
        return qualified_placement_node(row, actor, scope_detail=scope_detail)
    except NodeConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except NodeForbidden as exc:
        raise HTTPException(403, str(exc)) from None


def _require_profile(limits: ResourceLimits, minimum: ProfileLimits) -> None:
    requested = ProfileLimits(limits.memory_bytes, limits.cpu_millis, limits.pids)
    if not requested.covers(minimum):
        raise HTTPException(422, "Module limits must include its complete execution profile")


def operation_summary(
    row: NodeOperationRow, diagnostic: FailureDiagnostic | None = None
) -> PlacementOperationSummary:
    return PlacementOperationSummary.model_validate(
        operation_view(row, diagnostic), from_attributes=True
    )


async def project_workspace_binding(
    tx: AsyncSession,
    mount: WorkspaceMount | None,
    *,
    module: str,
    node_uuid: UUID,
    project_uuid: UUID,
    private_storage_uuid: UUID,
) -> WorkspaceMount | None:
    try:
        return await require_project_workspace(
            tx,
            mount,
            module=module,
            node_uuid=node_uuid,
            project_uuid=project_uuid,
            private_storage_uuid=private_storage_uuid,
        )
    except NodeInvalid as exc:
        raise HTTPException(422, str(exc)) from None
    except NodeConflict as exc:
        raise HTTPException(409, str(exc)) from None


class PlacementManager:
    def __init__(
        self,
        resolve_database: Callable[[], PlatformDatabase | None],
        authorize: Callable[[NodeCommand], Awaitable[OperatorAuthority]],
        remote: NodeExecutionControl | None = None,
    ) -> None:
        self.resolve_database, self.authorize = resolve_database, authorize
        self.remote = remote
        self.tasks: dict[UUID, asyncio.Task[None]] = {}

    async def close(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()

    def _database(self) -> PlatformDatabase:
        database = self.resolve_database()
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        return database

    def start(self, command: NodeCommand, operation: UUID, dispatch: bool) -> None:
        if operation in self.tasks:
            return
        require_placement_capacity(len(self.tasks))
        task = asyncio.create_task(self.run(command, operation, dispatch))
        self.tasks[operation] = task
        task.add_done_callback(lambda _done: self.tasks.pop(operation, None))

    async def project_list(self, command: NodeCommand, expiry: datetime) -> JSONResponse:
        data = command.module
        if data is None:
            raise HTTPException(422, "Exact module management command required")
        query = ReadProjectPlacements(
            SqlPlacementReader(self._database()), lambda: datetime.now(UTC)
        )
        try:
            items = await query.execute(
                command.project_uuid, data.node_uuid, frozenset(self.tasks), expiry
            )
        except NodeForbidden as exc:
            raise HTTPException(403, str(exc)) from None
        return placement_list_response(items)

    async def command(self, command: NodeCommand, expiry: datetime) -> JSONResponse:
        if command.module is None:
            raise HTTPException(422, "Exact module management command required")
        if command.module.action == "placements":
            return await self.project_list(command, expiry)
        if command.module.action == "recover":
            try:
                return await self.recover(command, expiry)
            except IntegrityError:
                raise HTTPException(409, "Concurrent recovery; retry the same operation") from None
        if command.module.action == "update":
            try:
                return await self.update(command, expiry)
            except IntegrityError:
                raise HTTPException(
                    409, "Concurrent placement update; retry the same operation"
                ) from None
        if command.module.action == "reconcile":
            operation_uuid = command.module.target_operation_uuid
            if operation_uuid is None:
                raise HTTPException(422, "Exact operation identifier required")
            return await self._reconcile(command, operation_uuid)
        value = command.module.placement
        if value is None:
            raise HTTPException(422, "Exact placement command required")
        return await self._place(command, value, expiry)

    async def _reconcile(self, command: NodeCommand, operation_uuid: UUID) -> JSONResponse:
        async with self._database().transaction() as tx:
            row = await tx.get(NodeOperationRow, operation_uuid)
            placement = await tx.get(NodeModuleRow, row.placement_uuid) if row else None
            if row is None or placement is None or placement.project_uuid != command.project_uuid:
                raise HTTPException(404, "Project operation not found")
            result = operation_summary(row, await operation_diagnostic(tx, row))
        self.start(command, operation_uuid, False)
        return placement_operation_response(result)

    async def _place(
        self, command: NodeCommand, value: PlacementInput, expiry: datetime
    ) -> JSONResponse:
        actor, _ = await self.authorize(command)
        fingerprint = hashlib.sha256(
            json.dumps(
                value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        dispatch = False
        try:
            async with self._database().transaction() as tx:
                existing = await tx.get(NodeOperationRow, command.operation_uuid)
                if existing:
                    placement = await tx.get(NodeModuleRow, existing.placement_uuid)
                    if (
                        placement is None
                        or existing.actor_uuid != command.actor_uuid
                        or placement.project_uuid != command.project_uuid
                        or placement.id != value.id
                        or placement.configuration.intent_digest != fingerprint
                    ):
                        raise HTTPException(409, "Placement operation identity conflicts")
                    result = operation_summary(existing, await operation_diagnostic(tx, existing))
                else:
                    require_placement_capacity(len(self.tasks))
                    node = await tx.scalar(
                        select(NodeRow).where(NodeRow.id == value.node_uuid).with_for_update()
                    )
                    node = _placement_node(node, actor)
                    try:
                        approved = await approved_placement_release(tx, value.release_uuid)
                    except CatalogError as exc:
                        raise HTTPException(409, str(exc)) from None
                    definition = approved.definition
                    _require_profile(value.limits, definition.minimum_limits)
                    if await tx.get(NodeModuleRow, value.id) is not None:
                        raise HTTPException(409, "Placement already exists")
                    binding = await tx.scalar(
                        select(ProjectModuleBindingRow).where(
                            ProjectModuleBindingRow.project_uuid == command.project_uuid,
                            ProjectModuleBindingRow.logical_key == definition.key,
                        )
                    )
                    if binding:
                        raise HTTPException(409, "Project already has this MCP placement")
                    storage_uuid = await ensure_project_storage(
                        tx, node.id, command.project_uuid, definition.storage_purpose
                    )
                    project_workspace = await project_workspace_binding(
                        tx,
                        value.project_workspace,
                        module=definition.key,
                        node_uuid=node.id,
                        project_uuid=command.project_uuid,
                        private_storage_uuid=storage_uuid,
                    )
                    # Public execution verifier only; the private key never enters this service.
                    public = await asyncio.to_thread(
                        Path(os.environ["RESOURCES_ACCESS_VERIFY_KEY_FILE"]).read_text
                    )
                    from projects.runtime_policy import resolved_configuration

                    spec = Deployment(
                        id=value.id,
                        node_uuid=node.id,
                        project_uuid=command.project_uuid,
                        release=approved.spec,
                        limits=value.limits,
                        workspace=WorkspaceMount(id=storage_uuid),
                        effect_verify_key=public,
                        configuration=await resolved_configuration(
                            tx, node.id, value.configuration
                        ),
                        project_workspace=project_workspace,
                    )
                    created = await create_placement_intent(
                        tx,
                        PlacementCreationIntent(
                            command.operation_uuid,
                            command.actor_uuid,
                            value.name,
                            approved.id,
                            fingerprint,
                            spec,
                        ),
                    )
                    result = PlacementOperationSummary.model_validate(created, from_attributes=True)
                    dispatch = True
                if expiry <= datetime.now(UTC):
                    raise HTTPException(403, "Current Platform proof required")
            # Existing intent can have reached the node even when its acknowledgement was lost.
            # A client retry observes the durable node journal; it never issues Apply again.
            self.start(command, command.operation_uuid, dispatch)
            return placement_operation_response(result)
        except NodeInvalid as exc:
            raise HTTPException(422, str(exc)) from None
        except IntegrityError:
            raise HTTPException(
                409, "Concurrent placement or workspace operation; retry same operation"
            ) from None

    async def recover(self, command: NodeCommand, expiry: datetime) -> JSONResponse:
        if command.module is None or command.module.recover is None:
            raise HTTPException(422, "Exact recovery command required")
        value = command.module.recover
        actor, _ = await self.authorize(command)
        intent = RecoveryIntent(
            command.operation_uuid,
            command.actor_uuid,
            command.project_uuid,
            value.id,
            value.expected_sequence,
        )
        recover = RecoverPlacement(
            SqlPlacementRecoveryTransactions(self._database()),
            lambda: len(self.tasks),
            lambda: datetime.now(UTC),
        )
        try:
            outcome = await recover.execute(intent, actor, expiry)
        except NodeMissing as exc:
            raise HTTPException(404, str(exc)) from None
        except (NodeConflict, CatalogError) as exc:
            raise HTTPException(409, str(exc)) from None
        except NodeForbidden as exc:
            raise HTTPException(403, str(exc)) from None
        except NodeInvalid as exc:
            raise HTTPException(422, str(exc)) from None
        except PlacementReconciliationBusy as exc:
            raise HTTPException(429, str(exc)) from None
        self.start(command, UUID(outcome.operation.id), outcome.dispatch)
        return placement_operation_response(
            PlacementOperationSummary.model_validate(outcome.operation, from_attributes=True)
        )

    async def update(self, command: NodeCommand, expiry: datetime) -> JSONResponse:
        if command.module is None or command.module.update is None:
            raise HTTPException(422, "Exact placement update required")
        value = command.module.update
        actor, _ = await self.authorize(command)
        intent = UpdateIntent(
            command.operation_uuid,
            command.actor_uuid,
            command.project_uuid,
            value.id,
            value.release_uuid,
            value.expected_sequence,
        )
        update = UpdatePlacement(
            SqlPlacementUpdateTransactions(self._database()),
            lambda: len(self.tasks),
            lambda: datetime.now(UTC),
        )
        try:
            outcome = await update.execute(intent, value, actor, expiry)
        except NodeMissing as exc:
            raise HTTPException(404, str(exc)) from None
        except (NodeConflict, CatalogError) as exc:
            raise HTTPException(409, str(exc)) from None
        except NodeForbidden as exc:
            raise HTTPException(403, str(exc)) from None
        except NodeInvalid as exc:
            raise HTTPException(422, str(exc)) from None
        except PlacementReconciliationBusy as exc:
            raise HTTPException(429, str(exc)) from None
        self.start(command, command.operation_uuid, outcome.dispatch)
        return placement_operation_response(
            PlacementOperationSummary.model_validate(outcome.operation, from_attributes=True)
        )

    @staticmethod
    def audit(
        tx: AsyncSession,
        operation: NodeOperationRow,
        placement: NodeModuleRow,
        phase: str,
        diagnostic: FailureDiagnostic | None = None,
        restored: Deployment | None = None,
    ) -> None:
        audit_placement(tx, operation, placement, phase, diagnostic, restored)

    async def save(
        self,
        operation_id: UUID,
        payload: NodeReply,
        *,
        inventory: NodeReply | None = None,
    ) -> bool:
        if not isinstance(payload, NodeOperation):
            raise ValueError("Signed node operation receipt required")
        observation = payload
        async with self._database().transaction() as tx:
            row = await tx.scalar(
                select(NodeOperationRow)
                .where(NodeOperationRow.id == operation_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("Operation disappeared")
            placement = await tx.get(NodeModuleRow, row.placement_uuid)
            if placement is None:
                raise ValueError("Placement disappeared")
            operation = OperationState(row.id, row.sequence, row.phase, row.error_code)
            receipt = OperationReceipt(
                observation.operation_uuid,
                observation.sequence,
                observation.phase,
                observation.error,
            )
            receipt.validate_for(operation, placement.sequence)
            previous_diagnostic = await operation_diagnostic(tx, row)
            diagnostic = previous_diagnostic or (
                diagnostic_payload(observation.diagnostic)
                if observation.diagnostic is not None
                else None
            )
            restored = await approved_restoration(tx, placement, row, payload, inventory)
            recovered = restored is not None and (
                placement.state != "ready" or placement.limits != restored.limits
            )
            decision = reconcile_receipt(
                operation,
                receipt,
                placement_sequence=placement.sequence,
                restoration_verified=restored is not None,
                restoration_changes_projection=recovered,
                diagnostic_changed=diagnostic != previous_diagnostic,
                first_diagnostic=previous_diagnostic is None and diagnostic is not None,
            )
            if decision.update_operation:
                row.phase, row.error_code = receipt.phase, receipt.error
                row.updated_at = datetime.now(UTC)
            if decision.placement_state is not None:
                placement.state = decision.placement_state
            if decision.apply_desired_release:
                placement.applied_release_uuid = placement.desired_release_uuid
            if decision.restore_limits and restored is not None:
                placement.limits = restored.limits
            if decision.audit:
                audited_restoration = restored if decision.restore_limits else None
                self.audit(tx, row, placement, row.phase, diagnostic, restored=audited_restoration)
            return decision.terminal

    async def _mark_uncertain(self, operation_uuid: UUID) -> None:
        # Never replay uncertain remote effects. Keep the committed intent for
        # explicit reconciliation against independently signed peer evidence.
        async with self._database().transaction() as tx:
            row = await tx.get(NodeOperationRow, operation_uuid)
            if row is None or row.phase in {"succeeded", "failed"}:
                return
            row.phase = "unknown"
            row.error_code = "NODE_RECONCILIATION_REQUIRED"
            row.updated_at = datetime.now(UTC)
            placement = await tx.get(NodeModuleRow, row.placement_uuid)
            if placement is None:
                raise ValueError("Placement disappeared")
            self.audit(tx, row, placement, "unknown")

    async def run(self, command: NodeCommand, operation_id: UUID, dispatch: bool) -> None:
        try:
            await self.authorize(command)
            async with self._database().transaction() as tx:
                target = await execution_target(tx, operation_id, command.project_uuid)
            if target is None:
                return

            async def save_receipt(payload: NodeReply, inventory: NodeReply | None) -> bool:
                return await self.save(operation_id, payload, inventory=inventory)

            reconciler = ReconcilePlacement(
                self.remote or NodeControl.from_environment(), target, operation_id, save_receipt
            )
            await reconciler.execute(dispatch=dispatch)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._mark_uncertain(operation_id)
