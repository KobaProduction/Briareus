"""Typed Protobuf wire adapters. Canonical signatures remain transport independent."""
import base64
from datetime import UTC

from . import node_pb2 as pb
from .models import Deployment, NodeRecord
from .control import ControlCommand

MODULE = {"files":1,"terminal":2,"web":3,"svc":4,"infrastructure":5,"reverse":6,"serena":8}
ACTION = {name: index for index, name in enumerate(("", "inventory", "configure", "apply", "status", "watch"))}
SCOPE = {"personal":pb.PERSONAL, "team":pb.TEAM, "shared":pb.SHARED}
LIFECYCLE = {"stateless":pb.STATELESS, "sessionful":pb.SESSIONFUL}


def known(message):
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    if clean.SerializeToString(deterministic=True) != message.SerializeToString(deterministic=True):
        raise ValueError("Unknown node protocol field")


def select(mapping, value):
    try:
        return next(key for key, number in mapping.items() if key and number == value)
    except StopIteration:
        raise ValueError("Unknown node protocol enum") from None


def limits(value):
    return {key:getattr(value,key) for key in ("memory_bytes","cpu_millis","pids")}


def encode_record(record):
    value=pb.NodeRecord(uuid=str(record.id),name=record.name,scope=SCOPE[record.scope.kind],
        budget=pb.Budget(total=pb.Limits(**record.budget.total.model_dump()),reserved=pb.Limits(**record.budget.reserved.model_dump())),
        enabled=record.enabled,shared_use=record.shared_use,shared_manage=record.shared_manage)
    if record.scope.owner_uuid:
        value.owner_uuid=str(record.scope.owner_uuid)
    value.created_at.FromDatetime(record.created_at)
    return value


def decode_record(value):
    if not value.HasField("created_at"):
        raise ValueError("Node creation time required")
    return NodeRecord(id=value.uuid,name=value.name,scope={"kind":select(SCOPE,value.scope),
        "owner_uuid":value.owner_uuid if value.HasField("owner_uuid") else None},
        budget={"total":limits(value.budget.total),"reserved":limits(value.budget.reserved)},
        enabled=value.enabled,shared_use=value.shared_use,shared_manage=value.shared_manage,
        created_at=value.created_at.ToDatetime(tzinfo=UTC))


def encode_deployment(spec):
    release=spec.release
    value=pb.Deployment(uuid=str(spec.id),node_uuid=str(spec.node_uuid),project_uuid=str(spec.project_uuid),
        release=pb.Release(module=MODULE[release.module],image=release.image,port=release.port,
            health_path=release.health_path,run_as=release.run_as,lifecycle=LIFECYCLE[release.lifecycle]),
        limits=pb.Limits(**spec.limits.model_dump()),enabled=spec.enabled)
    if spec.workspace:
        value.workspace.CopyFrom(pb.Workspace(uuid=str(spec.workspace.id),read_only=spec.workspace.read_only))
    if spec.project_workspace:
        value.project_workspace.CopyFrom(pb.Workspace(uuid=str(spec.project_workspace.id),read_only=spec.project_workspace.read_only))
    if spec.effect_verify_key:
        value.effect_verify_key=spec.effect_verify_key
    if spec.configuration is not None:
        if spec.configuration.browser is not None:
            value.configuration.browser.CopyFrom(pb.BrowserConfiguration(**spec.configuration.browser.model_dump(exclude_none=True)))
        if spec.configuration.serena is not None:
            value.configuration.serena.CopyFrom(pb.SerenaConfiguration(**spec.configuration.serena.model_dump()))
        if spec.configuration.network is not None:
            value.configuration.network.CopyFrom(pb.NetworkConfiguration(**spec.configuration.network.model_dump()))
        if spec.configuration.runtime_policy is not None:
            policy=spec.configuration.runtime_policy
            value.configuration.runtime_policy.CopyFrom(pb.RuntimePolicy(**policy.model_dump(exclude_none=True)))
        value.configuration.SetInParent()
    return value


def decode_deployment(value):
    release=value.release
    configuration=None
    if value.HasField("configuration"):
        configuration={}
        if value.configuration.HasField("runtime_policy"):
            policy=value.configuration.runtime_policy
            configuration["runtime_policy"]={field.name:getattr(policy,field.name) if policy.HasField(field.name) else None for field in policy.DESCRIPTOR.fields}
        for field in ("browser","serena","network"):
            if value.configuration.HasField(field):
                item=getattr(value.configuration,field)
                configuration[field]={descriptor.name:(getattr(item,descriptor.name) if not descriptor.has_presence or item.HasField(descriptor.name) else None) for descriptor in item.DESCRIPTOR.fields}
    return Deployment(id=value.uuid,node_uuid=value.node_uuid,project_uuid=value.project_uuid,
        release={"module":select(MODULE,release.module),"image":release.image,"port":release.port,
            "health_path":release.health_path,"run_as":release.run_as,"lifecycle":select(LIFECYCLE,release.lifecycle)},
        limits=limits(value.limits),enabled=value.enabled,
        workspace={"id":value.workspace.uuid,"read_only":value.workspace.read_only} if value.HasField("workspace") else None,
        project_workspace={"id":value.project_workspace.uuid,"read_only":value.project_workspace.read_only} if value.HasField("project_workspace") else None,
        effect_verify_key=value.effect_verify_key if value.HasField("effect_verify_key") else None,
        configuration=configuration)


def encode_command(command, signature):
    value=pb.Command(node_uuid=str(command.node_uuid),operation_uuid=str(command.operation_uuid),
        action=ACTION[command.action],sequence=command.sequence,issued_at=command.issued_at,
        expires_at=command.expires_at,after_event=command.after_event)
    if command.deployment:
        value.deployment.CopyFrom(encode_deployment(command.deployment))
    if command.node_record:
        value.node_record.CopyFrom(encode_record(command.node_record))
    return pb.SignedCommand(command=value,signature=signature)


def decode_command(envelope):
    known(envelope)
    value=envelope.command
    return ControlCommand(node_uuid=value.node_uuid,operation_uuid=value.operation_uuid,
        action=select(ACTION,value.action),sequence=value.sequence,issued_at=value.issued_at,
        expires_at=value.expires_at,after_event=value.after_event,
        deployment=decode_deployment(value.deployment) if value.HasField("deployment") else None,
        node_record=decode_record(value.node_record) if value.HasField("node_record") else None)


def encode_operation(value):
    result=pb.Operation(operation_uuid=value["operation_uuid"],sequence=value["sequence"],phase=value["phase"])
    if value["error"] is not None:
        result.error=value["error"]
    if value.get("diagnostic") is not None:
        from .diagnostics import diagnostic_wire
        result.diagnostic.CopyFrom(pb.FailureDiagnostic(**diagnostic_wire(value["diagnostic"])))
    return result


def decode_operation(value):
    result = {"operation_uuid":value.operation_uuid,"sequence":value.sequence,"phase":value.phase,
        "error":value.error if value.HasField("error") else None}
    if value.HasField("diagnostic"):
        from .diagnostics import diagnostic_wire
        details = value.diagnostic
        raw = {name:getattr(details,name) for name in ("stage","component","reason")}
        raw.update({name:getattr(details,name) for name in ("exit_code","health_status","oom_killed","health_exit_code") if details.HasField(name)})
        result["diagnostic"] = diagnostic_wire(raw)
    return result


def encode_reply(command, envelope):
    proof=dict(envelope["proof"])
    for key in ("request_digest","response_digest"):
        proof[key]=bytes.fromhex(proof[key])
    result=pb.SignedReply(proof=pb.ReplyProof(**proof),signature=base64.b64decode(envelope["signature"],validate=True))
    payload=envelope["result"]
    if set(payload)=={"error"} and isinstance(payload["error"],dict):
        result.failure.CopyFrom(pb.Failure(code=payload["error"]["code"]))
    elif command.action=="inventory":
        result.inventory.CopyFrom(pb.Inventory(node_uuid=payload["node_uuid"],enabled=payload["enabled"],
            sequence=payload["sequence"],event_cursor=payload["event_cursor"],items=[pb.ObservedModule(placement_uuid=item["placement_uuid"],
                fingerprint=item["fingerprint"],running=item["running"],ready=item["ready"],limits=pb.Limits(**item["limits"]))
                for item in payload["items"]]))
    elif command.action=="configure":
        result.configuration.CopyFrom(pb.Configuration(**payload))
    else:
        result.operation.CopyFrom(encode_operation(payload))
    return result


def decode_reply(value):
    known(value)
    proof={name:getattr(value.proof,name) for name in ("node_uuid","operation_uuid","status_code","issued_at","expires_at")}
    proof.update(request_digest=value.proof.request_digest.hex(),response_digest=value.proof.response_digest.hex())
    kind=value.WhichOneof("result")
    if kind=="failure":
        payload={"error":{"code":value.failure.code}}
    elif kind=="configuration":
        payload={"node_uuid":value.configuration.node_uuid,"enabled":value.configuration.enabled,"sequence":value.configuration.sequence}
    elif kind=="inventory":
        inventory=value.inventory
        payload={"node_uuid":inventory.node_uuid,"enabled":inventory.enabled,"sequence":inventory.sequence,
            "event_cursor":inventory.event_cursor,
            "items":[{"placement_uuid":item.placement_uuid,"fingerprint":item.fingerprint,"running":item.running,
                "ready":item.ready,"limits":limits(item.limits)} for item in inventory.items]}
    elif kind=="operation":
        payload=decode_operation(value.operation)
    else:
        raise ValueError("Typed node reply required")
    return {"proof":proof,"signature":base64.b64encode(value.signature).decode(),"result":payload}
