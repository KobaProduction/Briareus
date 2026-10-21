"""Operator-owned immutable releases using approved build/execution definitions."""
import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from node_protocol.catalog import ARTIFACTS, LOGICAL_MODULES
from projects._node_persistence import ModuleArtifactRow, ModuleReleaseRow
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow


def release_summary(row):
    return {"id":str(row.id),"module":row.artifact_key,"source_commit":row.source_commit,
        "input_fingerprint":row.input_fingerprint,"image":row.image_reference,"platform":row.platform,
        "state":row.state,"created_at":row.created_at.isoformat()}


def reviewed_input_upgrade(artifact, definition):
    """One owner-approved source-closure correction, never a general auto-upgrade.

    The unified Analysis image now copies its maintained radare2 adapter source.
    Existing release rows and immutable image/input fingerprints stay untouched.
    """
    if artifact.key != "reverse" or definition.key != "reverse" or not artifact.enabled:
        return False
    current = definition.inputs
    added = "hands/radare2/src/radare2_hand/**"
    if current.get("paths", []).count(added) != 1:
        return False
    previous = deepcopy(current)
    previous["paths"].remove(added)
    if artifact.inputs != previous:
        return False
    artifact.inputs = deepcopy(current)
    return True


async def catalog_command(command, *, database, cipher, expiry):
    data=command.module
    if data.action=="catalog":
        async with database.transaction() as tx:
            rows=list(await tx.scalars(select(ModuleReleaseRow).where(ModuleReleaseRow.state=="published",
                ModuleReleaseRow.artifact_key.in_(tuple(ARTIFACTS)))
                .order_by(ModuleReleaseRow.created_at.desc()).limit(100)))
            if expiry<=datetime.now(UTC):
                raise HTTPException(403,"Current Platform proof required")
            return JSONResponse({"modules":[{"key":item.key,"name":item.name,"components":list(item.components)}
                for item in LOGICAL_MODULES],"artifacts":[{"key":item.key,"name":item.name,"node_adapter":item.node_adapter,
                "lifecycle":item.lifecycle,"workspace":item.workspace,"inputs":item.inputs,
                "minimum_limits":item.minimum_limits,"default_limits":item.default_limits} for item in ARTIFACTS.values()],
                "releases":[release_summary(row) for row in rows]})
    value=data.publication
    definition=ARTIFACTS.get(value.module)
    if definition is None:
        raise HTTPException(422,"Unknown deployable module")
    if not definition.node_adapter:
        raise HTTPException(409,"This Hand's node effect adapter is not ready")
    try:
        allowed=json.loads(os.environ.get("RESOURCES_RELEASE_REGISTRIES","[]"))
        if not isinstance(allowed,list) or any(not isinstance(item,str) for item in allowed) or value.image.split("/",1)[0] not in allowed:
            raise ValueError
    except (ValueError,TypeError):
        raise HTTPException(422,"Image registry not approved for publication") from None
    fingerprint=hashlib.sha256(json.dumps(command.model_dump(mode="json",exclude={"identity_expires_at"}),
        sort_keys=True,separators=(",",":")).encode()).hexdigest()
    action="node.module.publish"
    try:
        async with database.transaction() as tx:
            receipt=await tx.scalar(select(OwnerCommandRow).where(OwnerCommandRow.operation_uuid==command.operation_uuid,
                OwnerCommandRow.operation==action))
            if receipt:
                if (receipt.fingerprint!=fingerprint or receipt.actor_scope!=str(command.actor_uuid)
                    or receipt.project_scope!=str(command.project_uuid) or receipt.state!="completed"):
                    raise HTTPException(409,"Publication operation conflicts")
                outcome=json.loads(cipher.decrypt(receipt.encrypted_outcome.encode()))
                if outcome["fingerprint"]!=fingerprint or expiry<=datetime.now(UTC):
                    raise HTTPException(403,"Current publication authority required")
                return JSONResponse(outcome["result"])
            artifact=await tx.get(ModuleArtifactRow,value.module,with_for_update=True)
            definition_upgraded=False
            if artifact is None:
                artifact=ModuleArtifactRow(key=value.module,name=definition.name,inputs=definition.inputs,
                    configuration_contract={"kind":"approved_node_adapter"},
                    storage_contract={"workspace":definition.workspace,"purpose":definition.storage_purpose,
                        "retention":"persistent"},enabled=True)
                tx.add(artifact)
                await tx.flush()
            if artifact.enabled and artifact.inputs!=definition.inputs:
                definition_upgraded=reviewed_input_upgrade(artifact,definition)
            if not artifact.enabled or artifact.inputs!=definition.inputs:
                raise HTTPException(409,"Artifact definition changed; explicit approval required")
            if await tx.get(ModuleReleaseRow,value.id) is not None:
                raise HTTPException(409,"Published release identity is immutable")
            row=ModuleReleaseRow(id=value.id,artifact_key=value.module,source_commit=value.source_commit,
                input_fingerprint=value.input_fingerprint,platform=value.platform,image_reference=value.image,
                state="published",storage_compatibility="workspace" if definition.workspace else "none")
            tx.add(row)
            await tx.flush()
            result={"release":release_summary(row)}
            if expiry<=datetime.now(UTC):
                raise HTTPException(403,"Current Platform proof required")
            tx.add(OwnerCommandRow(operation_uuid=command.operation_uuid,actor_scope=str(command.actor_uuid),
                project_scope=str(command.project_uuid),operation=action,key=str(command.operation_uuid),
                fingerprint=fingerprint,expected_owner_revision="0",state="completed",
                encrypted_outcome=cipher.encrypt(json.dumps({"fingerprint":fingerprint,"result":result}).encode()).decode(),
                expires_at=datetime.now(UTC)+timedelta(days=7)))
            tx.add(OwnerAuditRow(operation_uuid=command.operation_uuid,actor_user_id=command.actor_uuid,
                project_id=command.project_uuid,action=action,object_id=str(row.id),owner_revision="1",
                details={"artifact":value.module,"image":value.image,"source_commit":value.source_commit,
                    **({"definition_upgrade":"analysis-radare2-source-closure-20261021"} if definition_upgraded else {})}))
        return JSONResponse(result)
    except IntegrityError:
        raise HTTPException(409,"Release or publication operation already exists") from None
