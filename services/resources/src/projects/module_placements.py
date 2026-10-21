"""Durable project placement intent and signed gRPC reconciliation, without DB locks across I/O."""
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from node_protocol import Deployment, ModuleRelease, WorkspaceMount
from node_protocol.catalog import ARTIFACTS
from node_protocol.diagnostics import diagnostic_wire
from projects._catalog_ledger import OwnerAuditRow
from projects._node_persistence import (NodeRow,NodeModuleRow,NodeOperationRow,NodeStorageRow,
    ModuleReleaseRow,ModuleArtifactRow,ProjectModuleBindingRow)
from projects.node_control import NodeControl,NodeUnavailable
from projects.placement_recovery import current_spec, verified_restoration

ACTIVE={"queued","pulling","stopping","creating","checking","rolling_back"}
ERRORS={"UPDATE_FAILED","ROLLBACK_FAILED","CONTROLLER_INTERRUPTED","UNMANAGED_INSTANCE"}


def operation_summary(row, diagnostic=None):
    result = {"id":str(row.id),"placement_uuid":str(row.placement_uuid),"sequence":row.sequence,
        "phase":row.phase,"error":row.error_code,"updated_at":row.updated_at.isoformat()}
    if diagnostic is not None:
        result["diagnostic"] = diagnostic_wire(diagnostic)
    return result


async def operation_diagnostic(tx, row):
    # Owner audit metadata is separate from signed immutable deployment intent.
    # Scope all lookups to this exact operation, placement and actor.
    records = await tx.scalars(select(OwnerAuditRow).where(OwnerAuditRow.operation_uuid==row.id,
        OwnerAuditRow.object_id==str(row.placement_uuid),OwnerAuditRow.actor_user_id==row.actor_uuid,
        OwnerAuditRow.action.like("node.module.%")).order_by(OwnerAuditRow.created_at.desc()).limit(32))
    for record in records:
        value = record.details.get("diagnostic") if isinstance(record.details,dict) else None
        if value is not None:
            return diagnostic_wire(value)
    return None


async def project_workspace_binding(tx, mount, *, module, node_uuid, project_uuid, private_storage_uuid):
    if mount is None:
        return None
    if module not in {"web","reverse"} or mount.id == private_storage_uuid:
        raise HTTPException(422,"Web and Analysis can attach a separate project workspace")
    storage = await tx.get(NodeStorageRow,mount.id)
    if (storage is None or storage.node_uuid != node_uuid or storage.project_uuid != project_uuid
        or storage.purpose != "workspace" or storage.retention != "persistent"):
        raise HTTPException(409,"Shared workspace must belong to this project and node")
    return mount


class PlacementManager:
    def __init__(self, resolve_database, authorize, remote=None):
        self.resolve_database,self.authorize=resolve_database,authorize
        self.remote=remote
        self.tasks={}

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        self.tasks.clear()

    def start(self, command, operation, dispatch):
        if operation in self.tasks:
            return
        if len(self.tasks)>=16:
            raise HTTPException(429,"Node operation reconciliation is busy")
        task=asyncio.create_task(self.run(command,operation,dispatch))
        self.tasks[operation]=task
        task.add_done_callback(lambda done:self.tasks.pop(operation,None))

    async def project_list(self, command, expiry):
        data=command.module
        async with self.resolve_database().transaction() as tx:
            query=select(NodeModuleRow).where(NodeModuleRow.project_uuid==command.project_uuid)
            if data.node_uuid:
                query=query.where(NodeModuleRow.node_uuid==data.node_uuid)
            placements=list(await tx.scalars(query.order_by(NodeModuleRow.name,NodeModuleRow.id).limit(100)))
            result=[]
            for item in placements:
                operation=await tx.scalar(select(NodeOperationRow).where(NodeOperationRow.placement_uuid==item.id)
                    .order_by(NodeOperationRow.sequence.desc()).limit(1))
                summary=operation_summary(operation,await operation_diagnostic(tx,operation)) if operation else None
                if summary:
                    summary["reconciliation_required"]=(operation.phase not in {"succeeded","failed"}
                        and operation.id not in self.tasks)
                    summary["restored"]=(item.state=="ready" and operation.phase=="failed" and operation.error_code=="UPDATE_FAILED")
                applied_spec=current_spec(item,operation) if operation else None
                from projects.runtime_policy import resolved_configuration
                desired_configuration=await resolved_configuration(tx,item.node_uuid,applied_spec.configuration if applied_spec else None)
                policy_pending=bool(applied_spec and desired_configuration!=applied_spec.configuration)
                result.append({"runtime_policy_pending":policy_pending,"id":str(item.id),"node_uuid":str(item.node_uuid),"project_uuid":str(item.project_uuid),
                    "name":item.name,"module":item.artifact_key,"state":item.state,"sequence":item.sequence,
                    "limits":item.limits,"workspace_uuid":str(item.storage_uuid) if item.storage_uuid else None,
                    "release_uuid":str(item.applied_release_uuid if item.state=="ready" else item.desired_release_uuid),
                    "configuration":applied_spec.configuration.model_dump(mode="json") if applied_spec and applied_spec.configuration else None,
                    "project_workspace":applied_spec.project_workspace.model_dump(mode="json") if applied_spec and applied_spec.project_workspace else None,"operation":summary})
            if expiry<=datetime.now(UTC):
                raise HTTPException(403,"Current Platform proof required")
            return JSONResponse({"items":result})

    async def command(self, command, expiry):
        if command.module.action=="placements":
            return await self.project_list(command,expiry)
        if command.module.action=="recover":
            try:return await self.recover(command,expiry)
            except IntegrityError:raise HTTPException(409,"Concurrent recovery; retry the same operation") from None
        if command.module.action=="update":
            try:
                return await self.update(command,expiry)
            except IntegrityError:
                raise HTTPException(409,"Concurrent placement update; retry the same operation") from None
        if command.module.action=="reconcile":
            operation=command.module.target_operation_uuid
            async with self.resolve_database().transaction() as tx:
                row=await tx.get(NodeOperationRow,operation)
                placement=await tx.get(NodeModuleRow,row.placement_uuid) if row else None
                if placement is None or placement.project_uuid!=command.project_uuid:
                    raise HTTPException(404,"Project operation not found")
                result=operation_summary(row,await operation_diagnostic(tx,row))
            self.start(command,operation,False)
            return JSONResponse({"operation":result})
        value=command.module.placement
        actor,_=await self.authorize(command)
        fingerprint=hashlib.sha256(json.dumps(value.model_dump(mode="json"),sort_keys=True,separators=(",",":")).encode()).hexdigest()
        dispatch=False
        try:
            async with self.resolve_database().transaction() as tx:
                existing=await tx.get(NodeOperationRow,command.operation_uuid)
                if existing:
                    placement=await tx.get(NodeModuleRow,existing.placement_uuid)
                    if (existing.actor_uuid!=command.actor_uuid or placement.project_uuid!=command.project_uuid
                        or placement.id!=value.id or placement.configuration.get("intent_digest")!=fingerprint):
                        raise HTTPException(409,"Placement operation identity conflicts")
                    result=operation_summary(existing,await operation_diagnostic(tx,existing))
                else:
                    if len(self.tasks)>=16:
                        raise HTTPException(429,"Node operation reconciliation is busy")
                    node=await tx.scalar(select(NodeRow).where(NodeRow.id==value.node_uuid).with_for_update())
                    if node is None or node.deleted_at is not None or not node.enabled or not node.public_key:
                        raise HTTPException(409,"An enabled paired node is required")
                    # Operator status does not let a personal/team project silently borrow another scope.
                    if (node.scope=="personal" and str(node.owner_uuid)!=str(command.actor_uuid)
                        or node.scope=="team" and (actor.get("project_owner_kind")!="team"
                            or actor.get("project_owner_uuid")!=str(node.owner_uuid))):
                        raise HTTPException(403,"Node must belong to the current project scope")
                    release=await tx.get(ModuleReleaseRow,value.release_uuid)
                    artifact=await tx.get(ModuleArtifactRow,release.artifact_key) if release else None
                    definition=ARTIFACTS.get(release.artifact_key) if release else None
                    if (release is None or release.state!="published" or artifact is None or not artifact.enabled
                        or definition is None or not definition.node_adapter or release.platform!="linux/amd64"
                        or artifact.inputs!=definition.inputs):
                        raise HTTPException(409,"Approved published node adapter required")
                    if any(getattr(value.limits,key)<minimum for key,minimum in definition.minimum_limits.items()):
                        raise HTTPException(422,"Module limits must include its complete execution profile")
                    if await tx.get(NodeModuleRow,value.id) is not None:
                        raise HTTPException(409,"Placement already exists")
                    binding=await tx.scalar(select(ProjectModuleBindingRow).where(
                        ProjectModuleBindingRow.project_uuid==command.project_uuid,
                        ProjectModuleBindingRow.logical_key==definition.key))
                    if binding:
                        raise HTTPException(409,"Project already has this MCP placement")
                    storage=await tx.scalar(select(NodeStorageRow).where(NodeStorageRow.node_uuid==node.id,
                        NodeStorageRow.project_uuid==command.project_uuid,NodeStorageRow.purpose==definition.storage_purpose))
                    if storage is None:
                        storage=NodeStorageRow(id=uuid4(),node_uuid=node.id,project_uuid=command.project_uuid,
                            purpose=definition.storage_purpose,quota_bytes=1024**3,retention="persistent")
                        tx.add(storage)
                        await tx.flush()
                    project_workspace=await project_workspace_binding(tx,value.project_workspace,module=definition.key,
                        node_uuid=node.id,project_uuid=command.project_uuid,private_storage_uuid=storage.id)
                    # Public execution verification identity; private Access key never enters this service.
                    public=Path(os.environ["RESOURCES_ACCESS_VERIFY_KEY_FILE"]).read_text()
                    from projects.runtime_policy import resolved_configuration
                    spec=Deployment(id=value.id,node_uuid=node.id,project_uuid=command.project_uuid,
                        release=ModuleRelease(module=definition.key,image=release.image_reference,lifecycle=definition.lifecycle),
                        limits=value.limits,workspace=WorkspaceMount(id=storage.id),effect_verify_key=public,
                        configuration=await resolved_configuration(tx,node.id,value.configuration),project_workspace=project_workspace)
                    placement=NodeModuleRow(id=spec.id,node_uuid=node.id,project_uuid=command.project_uuid,
                        artifact_key=definition.key,name=value.name.strip(),desired_release_uuid=release.id,
                        storage_uuid=storage.id,limits=spec.limits.model_dump(),configuration={"intent_digest":fingerprint},
                        sequence=1,state="pending")
                    if not placement.name:
                        raise HTTPException(422,"Placement name required")
                    tx.add(placement)
                    await tx.flush()
                    tx.add(ProjectModuleBindingRow(project_uuid=command.project_uuid,placement_uuid=placement.id,logical_key=definition.key))
                    operation=NodeOperationRow(id=command.operation_uuid,node_uuid=node.id,placement_uuid=placement.id,
                        actor_uuid=command.actor_uuid,sequence=1,fingerprint=spec.fingerprint,desired=spec.model_dump(mode="json"),phase="queued")
                    tx.add(operation)
                    await tx.flush()
                    self.audit(tx,operation,placement,"queued")
                    result=operation_summary(operation)
                    dispatch=True
                if expiry<=datetime.now(UTC):
                    raise HTTPException(403,"Current Platform proof required")
            # Existing intent can have reached the node even when its acknowledgement was lost.
            # A client retry observes the durable node journal; it never issues Apply again.
            self.start(command,command.operation_uuid,dispatch)
            return JSONResponse({"operation":result})
        except IntegrityError:
            raise HTTPException(409,"Concurrent placement or workspace operation; retry same operation") from None

    async def recover(self, command, expiry):
        value=command.module.recover
        actor,_=await self.authorize(command)
        dispatch=False
        async with self.resolve_database().transaction() as tx:
            placement=await tx.scalar(select(NodeModuleRow).where(NodeModuleRow.id==value.id).with_for_update())
            if placement is None or placement.project_uuid!=command.project_uuid:
                raise HTTPException(404,"Project placement not found")
            existing=await tx.get(NodeOperationRow,command.operation_uuid)
            if existing:
                if (existing.actor_uuid!=command.actor_uuid or existing.placement_uuid!=value.id
                    or existing.sequence!=value.expected_sequence+1 or existing.previous!=existing.desired):
                    raise HTTPException(409,"Recovery operation identity conflicts")
            else:
                if len(self.tasks)>=16:raise HTTPException(429,"Node operation reconciliation is busy")
                if placement.sequence!=value.expected_sequence:raise HTTPException(409,"Placement changed")
                previous=await tx.scalar(select(NodeOperationRow).where(NodeOperationRow.placement_uuid==placement.id)
                    .order_by(NodeOperationRow.sequence.desc()).limit(1))
                if previous is None or previous.phase not in {"succeeded","failed"} or placement.state not in {"ready","failed"}:
                    raise HTTPException(409,"Reconcile the previous operation before recovery")
                node=await tx.get(NodeRow,placement.node_uuid)
                if node is None or not node.enabled or node.deleted_at or not node.public_key:
                    raise HTTPException(409,"An enabled paired node is required")
                if (node.scope=="personal" and str(node.owner_uuid)!=str(command.actor_uuid)
                    or node.scope=="team" and (actor.get("project_owner_kind")!="team" or actor.get("project_owner_uuid")!=str(node.owner_uuid))):
                    raise HTTPException(403,"Current node ownership required")
                spec=current_spec(placement,previous)
                release=await tx.get(ModuleReleaseRow,placement.applied_release_uuid)
                artifact=await tx.get(ModuleArtifactRow,placement.artifact_key)
                if (release is None or release.state!="published" or artifact is None or not artifact.enabled
                    or release.artifact_key!=placement.artifact_key or release.image_reference!=spec.release.image
                    or spec.id!=placement.id or spec.project_uuid!=command.project_uuid or spec.node_uuid!=placement.node_uuid
                    or spec.workspace is None or spec.workspace.id!=placement.storage_uuid):
                    raise HTTPException(409,"Current approved applied deployment required")
                storage=await tx.get(NodeStorageRow,placement.storage_uuid)
                if storage is None or storage.node_uuid!=node.id or storage.project_uuid!=command.project_uuid or storage.retention!="persistent":
                    raise HTTPException(409,"Current project storage required")
                await project_workspace_binding(tx,spec.project_workspace,module=spec.release.module,node_uuid=node.id,
                    project_uuid=command.project_uuid,private_storage_uuid=storage.id)
                wire=spec.model_dump(mode="json")
                placement.sequence+=1
                placement.state="updating"
                placement.desired_release_uuid=release.id
                existing=NodeOperationRow(id=command.operation_uuid,node_uuid=node.id,placement_uuid=placement.id,
                    actor_uuid=command.actor_uuid,sequence=placement.sequence,fingerprint=spec.fingerprint,
                    desired=wire,previous=wire,phase="queued")
                tx.add(existing);await tx.flush();self.audit(tx,existing,placement,"queued")
                dispatch=True
            if expiry<=datetime.now(UTC):raise HTTPException(403,"Current Platform proof required")
            result=operation_summary(existing,await operation_diagnostic(tx,existing))
        self.start(command,command.operation_uuid,dispatch)
        return JSONResponse({"operation":result})

    async def update(self, command, expiry):
        value=command.module.update
        dispatch=False
        actor,_=await self.authorize(command)
        async with self.resolve_database().transaction() as tx:
            existing=await tx.get(NodeOperationRow,command.operation_uuid)
            placement=await tx.scalar(select(NodeModuleRow).where(NodeModuleRow.id==value.id).with_for_update())
            if placement is None or placement.project_uuid!=command.project_uuid:
                raise HTTPException(404,"Project placement not found")
            if existing:
                release=await tx.get(ModuleReleaseRow,value.release_uuid)
                if (existing.actor_uuid!=command.actor_uuid or existing.placement_uuid!=value.id
                    or existing.sequence!=value.expected_sequence+1
                    or release is None or release.artifact_key!=placement.artifact_key
                    or existing.desired.get("release",{}).get("image")!=release.image_reference
                    or value.limits is not None and existing.desired.get("limits")!=value.limits.model_dump(mode="json")
                    or value.configuration is not None and existing.desired.get("configuration")!=value.configuration.model_dump(mode="json")
                    or "project_workspace" in value.model_fields_set and existing.desired.get("project_workspace") != (value.project_workspace.model_dump(mode="json") if value.project_workspace else None)):
                    raise HTTPException(409,"Update operation identity conflicts")
            else:
                if len(self.tasks)>=16:
                    raise HTTPException(429,"Node operation reconciliation is busy")
                if placement.sequence!=value.expected_sequence:
                    raise HTTPException(409,"Placement changed; select the current state")
                previous=await tx.scalar(select(NodeOperationRow).where(NodeOperationRow.placement_uuid==placement.id)
                    .order_by(NodeOperationRow.sequence.desc()).limit(1))
                if previous is None or previous.phase not in {"succeeded","failed"} or placement.state not in {"ready","failed"}:
                    raise HTTPException(409,"Reconcile the previous operation before updating")
                node=await tx.get(NodeRow,placement.node_uuid)
                if node is None or not node.enabled or node.deleted_at or not node.public_key:
                    raise HTTPException(409,"An enabled paired node is required")
                if (node.scope=="personal" and str(node.owner_uuid)!=str(command.actor_uuid)
                    or node.scope=="team" and (actor.get("project_owner_kind")!="team"
                        or actor.get("project_owner_uuid")!=str(node.owner_uuid))):
                    raise HTTPException(403,"Node must belong to the current project scope")
                release=await tx.get(ModuleReleaseRow,value.release_uuid)
                artifact=await tx.get(ModuleArtifactRow,placement.artifact_key)
                definition=ARTIFACTS.get(placement.artifact_key)
                if (release is None or release.state!="published" or release.artifact_key!=placement.artifact_key
                    or release.platform!="linux/amd64" or artifact is None or not artifact.enabled
                    or definition is None or not definition.node_adapter or artifact.inputs!=definition.inputs):
                    raise HTTPException(409,"Approved published node adapter required")
                spec=current_spec(placement,previous)
                storage=await tx.get(NodeStorageRow,placement.storage_uuid) if placement.storage_uuid else None
                if (spec.id!=placement.id or spec.node_uuid!=placement.node_uuid
                    or spec.project_uuid!=placement.project_uuid or spec.release.module!=definition.key
                    or spec.workspace is None or spec.workspace.id!=placement.storage_uuid
                    or storage is None or storage.node_uuid!=placement.node_uuid
                    or storage.project_uuid!=placement.project_uuid
                    or storage.purpose!=definition.storage_purpose or storage.retention!="persistent"):
                    raise HTTPException(409,"Current module storage owner binding required")
                project_workspace=value.project_workspace if "project_workspace" in value.model_fields_set else spec.project_workspace
                await project_workspace_binding(tx,spec.project_workspace,module=definition.key,node_uuid=node.id,
                    project_uuid=command.project_uuid,private_storage_uuid=storage.id)
                await project_workspace_binding(tx,project_workspace,module=definition.key,node_uuid=node.id,
                    project_uuid=command.project_uuid,private_storage_uuid=storage.id)
                configuration=value.configuration if value.configuration is not None else spec.configuration
                from projects.runtime_policy import resolved_configuration
                configuration=await resolved_configuration(tx,node.id,configuration)
                limits=value.limits if value.limits is not None else spec.limits
                if any(getattr(limits,key)<minimum for key,minimum in definition.minimum_limits.items()):
                    raise HTTPException(422,"Module limits must include its complete execution profile")
                if (spec.release.image==release.image_reference and configuration==spec.configuration and limits==spec.limits
                    and project_workspace==spec.project_workspace and previous.phase=="succeeded"):
                    raise HTTPException(409,"This image is already deployed")
                desired=Deployment.model_validate({**spec.model_dump(mode="json"),
                    "release":ModuleRelease(module=definition.key,image=release.image_reference,
                        lifecycle=definition.lifecycle).model_dump(mode="json"),
                    "configuration":configuration.model_dump(mode="json") if configuration is not None else None,
                    "project_workspace":project_workspace.model_dump(mode="json") if project_workspace is not None else None,
                    "limits":limits.model_dump(mode="json")})
                placement.sequence+=1
                placement.desired_release_uuid=release.id
                placement.limits=desired.limits.model_dump(mode="json")
                placement.state="updating"
                existing=NodeOperationRow(id=command.operation_uuid,node_uuid=placement.node_uuid,
                    placement_uuid=placement.id,actor_uuid=command.actor_uuid,sequence=placement.sequence,
                    fingerprint=desired.fingerprint,desired=desired.model_dump(mode="json"),
                    previous=spec.model_dump(mode="json"),phase="queued")
                tx.add(existing)
                await tx.flush()
                self.audit(tx,existing,placement,"queued")
                dispatch=True
            result=operation_summary(existing,await operation_diagnostic(tx,existing))
            if expiry<=datetime.now(UTC):
                raise HTTPException(403,"Current Platform proof required")
        # Dispatch only a newly committed intent. A retry observes its signed receipt.
        self.start(command,command.operation_uuid,dispatch)
        return JSONResponse({"operation":result})

    @staticmethod
    def audit(tx,operation,placement,phase,diagnostic=None,restored=None):
        details={"node_uuid":str(operation.node_uuid),"phase":phase}
        if diagnostic is not None:
            details["diagnostic"] = diagnostic_wire(diagnostic)
        if restored is not None:
            details["restored_fingerprint"] = restored.fingerprint
        tx.add(OwnerAuditRow(operation_uuid=operation.id,actor_user_id=operation.actor_uuid,
            project_id=placement.project_uuid,action="node.module."+phase,object_id=str(placement.id),
            owner_revision=str(operation.sequence),details=details))

    async def save(self, operation_id, payload, *, inventory=None):
        async with self.resolve_database().transaction() as tx:
            row=await tx.scalar(select(NodeOperationRow).where(NodeOperationRow.id==operation_id).with_for_update())
            if row is None:
                raise ValueError("Operation disappeared")
            if (payload.get("operation_uuid")!=str(row.id) or payload.get("sequence")!=row.sequence
                or payload.get("phase") not in ACTIVE|{"succeeded","failed"}
                or payload.get("error") not in ERRORS|{None}):
                raise ValueError("Signed operation selectors mismatch")
            placement=await tx.get(NodeModuleRow,row.placement_uuid)
            if placement.sequence!=row.sequence:
                raise ValueError("Operation no longer current")
            previous_diagnostic = await operation_diagnostic(tx,row)
            diagnostic = previous_diagnostic or (diagnostic_wire(payload["diagnostic"])
                if payload.get("diagnostic") is not None else None)
            if row.phase in {"succeeded","failed"} and (payload["phase"]!=row.phase or payload["error"]!=row.error_code):
                raise ValueError("Terminal operation receipt changed")
            recovery_node=await tx.get(NodeRow,row.node_uuid) if inventory is not None else None
            restored=verified_restoration(placement,row,payload,inventory,node=recovery_node)
            if restored is not None:
                release=await tx.get(ModuleReleaseRow,placement.applied_release_uuid)
                if release is None or release.image_reference!=restored.release.image or release.artifact_key!=placement.artifact_key:
                    restored=None
            recovered=restored is not None and (placement.state!="ready" or placement.limits!=restored.limits.model_dump(mode="json"))
            if row.phase in {"succeeded","failed"}:
                if recovered:
                    placement.state="ready";placement.limits=restored.limits.model_dump(mode="json")
                if recovered or previous_diagnostic is None and diagnostic is not None:
                    self.audit(tx,row,placement,row.phase,diagnostic,restored=restored if recovered else None)
                return True
            changed=row.phase!=payload["phase"] or row.error_code!=payload["error"] or diagnostic!=previous_diagnostic
            row.phase,row.error_code=payload["phase"],payload["error"]
            row.updated_at=datetime.now(UTC)
            placement.state="ready" if row.phase=="succeeded" else "failed" if row.phase=="failed" else "updating"
            if row.phase=="succeeded":
                placement.applied_release_uuid=placement.desired_release_uuid
            elif restored is not None:
                placement.state="ready";placement.limits=restored.limits.model_dump(mode="json")
            if changed:
                self.audit(tx,row,placement,row.phase,diagnostic,restored=restored)
            return row.phase in {"succeeded","failed"}

    async def run(self, command, operation_id, dispatch):
        database=self.resolve_database()
        try:
            await self.authorize(command)
            async with database.transaction() as tx:
                operation=await tx.get(NodeOperationRow,operation_id)
                placement=await tx.get(NodeModuleRow,operation.placement_uuid)
                node=await tx.get(NodeRow,operation.node_uuid)
                if placement.project_uuid!=command.project_uuid or node.deleted_at or not node.enabled or not node.public_key:
                    raise ValueError("Current enabled project node required")
                if operation.phase=="succeeded" or operation.phase=="failed" and operation.error_code!="UPDATE_FAILED":
                    return
                spec=Deployment.model_validate(operation.desired)
                endpoint,pin,sequence=node.endpoint,node.public_key,operation.sequence
            remote=self.remote or NodeControl.from_environment()
            options=dict(endpoint=endpoint,public_key=pin,node_uuid=spec.node_uuid,sequence=sequence)
            async def save_receipt(payload):
                # The failed receipt alone never proves that a prior worker
                # is usable. Obtain a fresh separately signed runtime view.
                recovered_inventory=None
                if payload.get("phase")=="failed" and payload.get("error")=="UPDATE_FAILED":
                    try:
                        recovered_inventory=await remote.call(**options,operation_uuid=uuid4())
                    except NodeUnavailable:
                        pass
                return await self.save(operation_id,payload,inventory=recovered_inventory)
            if dispatch:
                result=await remote.call(**options,operation_uuid=operation_id,action="apply",deployment=spec)
                if await save_receipt(result):
                    return
            inventory=await remote.call(**options,operation_uuid=uuid4())
            cursor=inventory["event_cursor"]
            status=await remote.call(**options,operation_uuid=operation_id,action="status")
            if await save_receipt(status):
                return
            async with asyncio.timeout(240):
                while True:
                    async for event in remote.watch(**options,operation_uuid=uuid4(),after_event=cursor):
                        cursor=event["cursor"]
                        if event["topic"]=="operation" and event["payload"].get("operation_uuid")==str(operation_id):
                            if await save_receipt(event["payload"]):
                                return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never replay uncertain remote effects; preserve intent for explicit signed reconciliation.
            async with database.transaction() as tx:
                row=await tx.get(NodeOperationRow,operation_id)
                if row and row.phase not in {"succeeded","failed"}:
                    row.phase="unknown"
                    row.error_code="NODE_RECONCILIATION_REQUIRED"
                    row.updated_at=datetime.now(UTC)
                    placement=await tx.get(NodeModuleRow,row.placement_uuid)
                    self.audit(tx,row,placement,"unknown")
