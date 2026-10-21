"""Project/node-owned workspace metadata; no worker or Files MCP dependency."""
import hashlib
import json
from datetime import UTC,datetime,timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from node_protocol.control import canonical
from projects._catalog_ledger import OwnerAuditRow,OwnerCommandRow
from projects._node_persistence import NodeRow,NodeStorageRow


def summary(row):
    return {"id":str(row.id),"node_uuid":str(row.node_uuid),"project_uuid":str(row.project_uuid),
        "purpose":row.purpose,"retention":row.retention}


async def workspace_command(command,*,database,cipher,actor,expiry):
    node_id=command.module.node_uuid
    ensure=command.module.action=="ensure_workspace"
    action="node.workspace.ensure"
    digest=hashlib.sha256(canonical({"node_uuid":str(node_id),"project_uuid":str(command.project_uuid)})).hexdigest()
    try:
        async with database.transaction() as tx:
            # The same node lock is used by placement storage initialization.
            # Unique(node,project,purpose) supplies the final concurrency fence.
            node=await tx.scalar(select(NodeRow).where(NodeRow.id==node_id).with_for_update())
            if node is None or node.deleted_at is not None or not node.enabled or not node.public_key:
                raise HTTPException(409,"An enabled paired node is required")
            if (node.scope=="personal" and str(node.owner_uuid)!=str(command.actor_uuid)
                or node.scope=="team" and (actor.get("project_owner_kind")!="team"
                    or actor.get("project_owner_uuid")!=str(node.owner_uuid))):
                raise HTTPException(403,"Node must belong to the current project scope")
            row=await tx.scalar(select(NodeStorageRow).where(NodeStorageRow.node_uuid==node_id,
                NodeStorageRow.project_uuid==command.project_uuid,NodeStorageRow.purpose=="workspace"))
            if row is not None and row.retention!="persistent":
                raise HTTPException(409,"Persistent project workspace required")
            if ensure:
                receipt=await tx.scalar(select(OwnerCommandRow).where(
                    OwnerCommandRow.operation_uuid==command.operation_uuid,OwnerCommandRow.operation==action))
                if receipt is not None:
                    if (receipt.fingerprint!=digest or receipt.actor_scope!=str(command.actor_uuid)
                        or receipt.project_scope!=str(command.project_uuid) or receipt.state!="completed"):
                        raise HTTPException(409,"Workspace operation identity conflicts")
                    outcome=json.loads(cipher.decrypt(receipt.encrypted_outcome.encode()))
                    if (outcome.get("digest")!=digest or outcome.get("operation")!=str(command.operation_uuid)
                        or row is None or outcome.get("result")!={"item":summary(row)}):
                        raise HTTPException(409,"Current workspace receipt unavailable")
                    result=outcome["result"]
                else:
                    if row is None:
                        row=NodeStorageRow(id=uuid4(),node_uuid=node_id,project_uuid=command.project_uuid,
                            purpose="workspace",quota_bytes=1024**3,retention="persistent")
                        tx.add(row)
                        await tx.flush()
                    result={"item":summary(row)}
                    tx.add(OwnerCommandRow(operation_uuid=command.operation_uuid,actor_scope=str(command.actor_uuid),
                        project_scope=str(command.project_uuid),operation=action,key=str(command.operation_uuid),fingerprint=digest,
                        expected_owner_revision="0",state="completed",expires_at=datetime.now(UTC)+timedelta(days=7),
                        encrypted_outcome=cipher.encrypt(json.dumps({"digest":digest,"operation":str(command.operation_uuid),
                            "result":result}).encode()).decode()))
                    tx.add(OwnerAuditRow(operation_uuid=command.operation_uuid,actor_user_id=command.actor_uuid,
                        project_id=command.project_uuid,action=action,object_id=str(row.id),owner_revision="1",
                        details={"node_uuid":str(node_id),"purpose":"workspace"}))
            else:
                result={"items":[summary(row)] if row else []}
            if expiry<=datetime.now(UTC):
                raise HTTPException(403,"Current Platform proof required")
        return JSONResponse(result,headers={"Cache-Control":"no-store"})
    except IntegrityError:
        raise HTTPException(409,"Concurrent workspace operation; retry the same operation") from None
