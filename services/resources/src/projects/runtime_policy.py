"""Operator runtime settings. Saving does not restart running project workers."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from projects._node_persistence import RuntimePolicyRow, NodeRow
from projects._catalog_ledger import OwnerCommandRow, OwnerAuditRow
from node_protocol.models import RuntimePolicy, RuntimePolicyOverrides, ModuleConfiguration


def resolve_policy(server=None,node=None):
    values=RuntimePolicy().model_dump()
    sources={key:"default" for key in values}
    for source,overrides in (("server",server),("node",node)):
        validated=RuntimePolicyOverrides.model_validate(overrides or {}).model_dump(exclude_unset=True)
        values.update(validated)
        sources.update({key:source for key in validated})
    return RuntimePolicy.model_validate(values),sources


async def resolved_configuration(tx,node_uuid,configuration):
    server=await tx.get(RuntimePolicyRow,"server")
    node=await tx.get(RuntimePolicyRow,"node:"+str(node_uuid))
    # No rows preserves immutable fingerprints of existing legacy deployments.
    if server is None and node is None:return configuration
    effective,_=resolve_policy(server.values if server else {},node.values if node else {})
    value=configuration.model_dump() if configuration else {}
    value["runtime_policy"]=effective.model_dump()
    return ModuleConfiguration.model_validate(value)


async def policy_command(command,*,database,cipher,expiry):
    if command.policy_scope=="node":
        if command.node_uuid is None:raise HTTPException(422,"Node required")
        key="node:"+str(command.node_uuid)
    else:
        if command.node_uuid is not None:raise HTTPException(422,"Server policy has no node")
        key="server"
    if command.module or command.registration or command.name or command.public_key or command.budget:
        raise HTTPException(422,"Exact runtime policy command required")
    reading=command.action=="runtime_policy_get"
    if reading and command.policy_values is not None:raise HTTPException(422,"Read cannot write policy")
    if not reading and (command.policy_values is None or command.expected_policy_sequence is None):
        raise HTTPException(422,"Explicit overrides and current sequence required")
    digest=hashlib.sha256(json.dumps(command.model_dump(mode="json",exclude={"identity_expires_at"}),sort_keys=True).encode()).hexdigest()
    async with database.transaction() as tx:
        # Missing rows cannot be locked by SELECT FOR UPDATE. Serialize first
        # creation and subsequent updates on the same canonical policy scope.
        await tx.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key":"runtime-policy:"+key})
        if command.node_uuid:
            node=await tx.get(NodeRow,command.node_uuid)
            if node is None or node.deleted_at is not None:raise HTTPException(404,"Node not found")
        row=await tx.scalar(select(RuntimePolicyRow).where(RuntimePolicyRow.scope_key==key).with_for_update())
        if not reading:
            prior=await tx.scalar(select(OwnerCommandRow).where(OwnerCommandRow.operation_uuid==command.operation_uuid,OwnerCommandRow.operation=="node.runtime_policy"))
            if prior:
                if prior.fingerprint!=digest or prior.actor_scope!=str(command.actor_uuid) or prior.project_scope!=str(command.project_uuid):
                    raise HTTPException(409,"Operation identity conflict")
                return JSONResponse(json.loads(cipher.decrypt(prior.encrypted_outcome.encode())))
            if command.expected_policy_sequence!=(row.sequence if row else 0):raise HTTPException(409,"Runtime settings changed")
            values=command.policy_values.model_dump(exclude_unset=True)
            if row is None:
                row=RuntimePolicyRow(scope_key=key,values=values,sequence=1);tx.add(row)
            else:row.values=values;row.sequence+=1
            await tx.flush()
        server=await tx.get(RuntimePolicyRow,"server")
        node=await tx.get(RuntimePolicyRow,"node:"+str(command.node_uuid)) if command.node_uuid else None
        effective,sources=resolve_policy(server.values if server else {},node.values if node else {})
        result={"runtime_policy":{"scope":command.policy_scope,"node_uuid":str(command.node_uuid) if command.node_uuid else None,
            "sequence":row.sequence if row else 0,"overrides":row.values if row else {},"effective":effective.model_dump(),
            "sources":sources,"applies_on":"placement_update"}}
        if expiry<=datetime.now(UTC):raise HTTPException(403,"Platform proof expired")
        if not reading:
            tx.add(OwnerCommandRow(operation_uuid=command.operation_uuid,actor_scope=str(command.actor_uuid),project_scope=str(command.project_uuid),
                operation="node.runtime_policy",key=str(command.operation_uuid),fingerprint=digest,expected_owner_revision=str(command.expected_policy_sequence),
                state="completed",encrypted_outcome=cipher.encrypt(json.dumps(result).encode()).decode(),expires_at=datetime.now(UTC)+timedelta(days=7)))
            tx.add(OwnerAuditRow(operation_uuid=command.operation_uuid,actor_user_id=command.actor_uuid,project_id=command.project_uuid,
                action="node.runtime_policy",object_id=key,owner_revision=str(row.sequence),details={"keys":list(row.values)}))
    return JSONResponse(result)
