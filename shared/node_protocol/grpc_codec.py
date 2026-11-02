"""Typed Protobuf wire adapters. Canonical signatures remain transport independent."""

import base64
from collections.abc import Mapping
from datetime import UTC
from uuid import UUID

from google.protobuf.message import Message

from . import node_pb2 as pb
from .browser_observation import BrowserObservationWire
from .control import ControlCommand, ReplyProof
from .diagnostics import FailureDiagnostic, diagnostic_payload
from .domain.observations import FailureFacts
from .grpc_browser_observation import (
    decode_observation,
    decode_selector,
    encode_observation,
    encode_selector,
)
from .models import (
    BrowserConfiguration,
    Deployment,
    ModuleConfiguration,
    NetworkConfiguration,
    NodeRecord,
    ResourceLimits,
    RuntimePolicy,
    SerenaConfiguration,
)
from .reply_wire import (
    ConfigurationWire,
    FailureCodeWire,
    FailureWire,
    InventoryWire,
    NodeReplyWire,
    ObservedModuleWire,
    OperationWire,
    ReplyPayload,
)

MODULE = {
    "files": pb.FILES,
    "terminal": pb.TERMINAL,
    "web": pb.WEB,
    "svc": pb.SVC,
    "infrastructure": pb.INFRASTRUCTURE,
    "reverse": pb.REVERSE,
    "serena": pb.SERENA,
}
ACTION = {
    "inventory": pb.INVENTORY,
    "configure": pb.CONFIGURE,
    "apply": pb.APPLY,
    "status": pb.STATUS,
    "watch": pb.WATCH,
    "observe_browser": pb.OBSERVE_BROWSER,
}
SCOPE = {"personal": pb.PERSONAL, "team": pb.TEAM, "shared": pb.SHARED}
LIFECYCLE = {"stateless": pb.STATELESS, "sessionful": pb.SESSIONFUL}


def known(message: Message) -> None:
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    if clean.SerializeToString(deterministic=True) != message.SerializeToString(deterministic=True):
        raise ValueError("Unknown node protocol field")


def select(mapping: Mapping[str, int], value: int) -> str:
    try:
        return next(key for key, number in mapping.items() if key and number == value)
    except StopIteration:
        raise ValueError("Unknown node protocol enum") from None


def limits(value: pb.Limits) -> ResourceLimits:
    return ResourceLimits(
        memory_bytes=value.memory_bytes, cpu_millis=value.cpu_millis, pids=value.pids
    )


def encode_record(record: NodeRecord) -> pb.NodeRecord:
    value = pb.NodeRecord(
        uuid=str(record.id),
        name=record.name,
        scope=SCOPE[record.scope.kind],
        budget=pb.Budget(
            total=pb.Limits(**record.budget.total.model_dump()),
            reserved=pb.Limits(**record.budget.reserved.model_dump()),
        ),
        enabled=record.enabled,
        shared_use=record.shared_use,
        shared_manage=record.shared_manage,
    )
    if record.scope.owner_uuid:
        value.owner_uuid = str(record.scope.owner_uuid)
    value.created_at.FromDatetime(record.created_at)
    return value


def decode_record(value: pb.NodeRecord) -> NodeRecord:
    if not value.HasField("created_at"):
        raise ValueError("Node creation time required")
    return NodeRecord.model_validate(
        {
            "id": value.uuid,
            "name": value.name,
            "scope": {
                "kind": select(SCOPE, value.scope),
                "owner_uuid": value.owner_uuid if value.HasField("owner_uuid") else None,
            },
            "budget": {
                "total": limits(value.budget.total),
                "reserved": limits(value.budget.reserved),
            },
            "enabled": value.enabled,
            "shared_use": value.shared_use,
            "shared_manage": value.shared_manage,
            "created_at": value.created_at.ToDatetime(tzinfo=UTC),
        }
    )


def encode_deployment(spec: Deployment) -> pb.Deployment:
    release = spec.release
    value = pb.Deployment(
        uuid=str(spec.id),
        node_uuid=str(spec.node_uuid),
        project_uuid=str(spec.project_uuid),
        release=pb.Release(
            module=MODULE[release.module],
            image=release.image,
            port=release.port,
            health_path=release.health_path,
            run_as=release.run_as,
            lifecycle=LIFECYCLE[release.lifecycle],
        ),
        limits=pb.Limits(**spec.limits.model_dump()),
        enabled=spec.enabled,
    )
    if spec.workspace:
        value.workspace.CopyFrom(
            pb.Workspace(uuid=str(spec.workspace.id), read_only=spec.workspace.read_only)
        )
    if spec.project_workspace:
        value.project_workspace.CopyFrom(
            pb.Workspace(
                uuid=str(spec.project_workspace.id), read_only=spec.project_workspace.read_only
            )
        )
    if spec.effect_verify_key:
        value.effect_verify_key = spec.effect_verify_key
    if spec.configuration is not None:
        if spec.configuration.browser is not None:
            value.configuration.browser.CopyFrom(
                pb.BrowserConfiguration(**spec.configuration.browser.model_dump(exclude_none=True))
            )
        if spec.configuration.serena is not None:
            value.configuration.serena.CopyFrom(
                pb.SerenaConfiguration(**spec.configuration.serena.model_dump())
            )
        if spec.configuration.network is not None:
            value.configuration.network.CopyFrom(
                pb.NetworkConfiguration(**spec.configuration.network.model_dump())
            )
        if spec.configuration.runtime_policy is not None:
            policy = spec.configuration.runtime_policy
            value.configuration.runtime_policy.CopyFrom(
                pb.RuntimePolicy(**policy.model_dump(exclude_none=True))
            )
        value.configuration.SetInParent()
    return value


def _decode_browser(value: pb.BrowserConfiguration) -> BrowserConfiguration:
    return BrowserConfiguration(
        external_enabled=value.external_enabled,
        external_mcp_url=value.external_mcp_url,
        call_timeout_seconds=value.call_timeout_seconds
        if value.HasField("call_timeout_seconds")
        else None,
        auto_disconnect_enabled=value.auto_disconnect_enabled,
        idle_timeout_seconds=value.idle_timeout_seconds,
        profile_dir_name=value.profile_dir_name,
        developer_access_enabled=value.developer_access_enabled,
    )


def _decode_policy(value: pb.RuntimePolicy) -> RuntimePolicy:
    return RuntimePolicy(
        execution_timeout_seconds=(
            value.execution_timeout_seconds if value.HasField("execution_timeout_seconds") else None
        ),
        web_max_tabs=value.web_max_tabs if value.HasField("web_max_tabs") else None,
        web_tab_idle_seconds=(
            value.web_tab_idle_seconds if value.HasField("web_tab_idle_seconds") else None
        ),
        terminal_idle_seconds=(
            value.terminal_idle_seconds if value.HasField("terminal_idle_seconds") else None
        ),
    )


def _decode_configuration(value: pb.ModuleConfiguration) -> ModuleConfiguration:
    return ModuleConfiguration(
        runtime_policy=_decode_policy(value.runtime_policy)
        if value.HasField("runtime_policy")
        else None,
        browser=_decode_browser(value.browser) if value.HasField("browser") else None,
        network=NetworkConfiguration.model_validate({"profile": value.network.profile})
        if value.HasField("network")
        else None,
        serena=SerenaConfiguration.model_validate(
            {
                "project_path": value.serena.project_path,
                "language_backend": value.serena.language_backend,
            }
        )
        if value.HasField("serena")
        else None,
    )


def decode_deployment(value: pb.Deployment) -> Deployment:
    release = value.release
    return Deployment.model_validate(
        {
            "id": value.uuid,
            "node_uuid": value.node_uuid,
            "project_uuid": value.project_uuid,
            "release": {
                "module": select(MODULE, release.module),
                "image": release.image,
                "port": release.port,
                "health_path": release.health_path,
                "run_as": release.run_as,
                "lifecycle": select(LIFECYCLE, release.lifecycle),
            },
            "limits": limits(value.limits),
            "enabled": value.enabled,
            "workspace": {"id": value.workspace.uuid, "read_only": value.workspace.read_only}
            if value.HasField("workspace")
            else None,
            "project_workspace": {
                "id": value.project_workspace.uuid,
                "read_only": value.project_workspace.read_only,
            }
            if value.HasField("project_workspace")
            else None,
            "effect_verify_key": value.effect_verify_key
            if value.HasField("effect_verify_key")
            else None,
            "configuration": _decode_configuration(value.configuration)
            if value.HasField("configuration")
            else None,
        }
    )


def encode_command(command: ControlCommand, signature: bytes) -> pb.SignedCommand:
    value = pb.Command(
        node_uuid=str(command.node_uuid),
        operation_uuid=str(command.operation_uuid),
        action=ACTION[command.action],
        sequence=command.sequence,
        issued_at=command.issued_at,
        expires_at=command.expires_at,
        after_event=command.after_event,
    )
    if command.deployment:
        value.deployment.CopyFrom(encode_deployment(command.deployment))
    if command.node_record:
        value.node_record.CopyFrom(encode_record(command.node_record))
    if command.browser_observation is not None:
        value.browser_observation.CopyFrom(encode_selector(command.browser_observation))
    return pb.SignedCommand(command=value, signature=signature)


def decode_command(envelope: pb.SignedCommand) -> ControlCommand:
    known(envelope)
    value = envelope.command
    return ControlCommand.model_validate(
        {
            "node_uuid": value.node_uuid,
            "operation_uuid": value.operation_uuid,
            "action": select(ACTION, value.action),
            "sequence": value.sequence,
            "issued_at": value.issued_at,
            "expires_at": value.expires_at,
            "after_event": value.after_event,
            "deployment": decode_deployment(value.deployment)
            if value.HasField("deployment")
            else None,
            "node_record": decode_record(value.node_record)
            if value.HasField("node_record")
            else None,
            "browser_observation": decode_selector(value.browser_observation)
            if value.HasField("browser_observation")
            else None,
        }
    )


def encode_diagnostic(value: FailureDiagnostic) -> pb.FailureDiagnostic:
    result = pb.FailureDiagnostic(stage=value.stage, component=value.component, reason=value.reason)
    if value.exit_code is not None:
        result.exit_code = value.exit_code
    if value.health_status is not None:
        result.health_status = value.health_status
    if value.oom_killed is not None:
        result.oom_killed = value.oom_killed
    if value.health_exit_code is not None:
        result.health_exit_code = value.health_exit_code
    return result


def encode_operation(payload: OperationWire) -> pb.Operation:
    result = pb.Operation(
        operation_uuid=str(payload.operation_uuid), sequence=payload.sequence, phase=payload.phase
    )
    if payload.error is not None:
        result.error = payload.error
    if payload.diagnostic is not None:
        result.diagnostic.CopyFrom(encode_diagnostic(payload.diagnostic))
    return result


def decode_diagnostic(value: pb.FailureDiagnostic) -> FailureDiagnostic:
    return diagnostic_payload(
        FailureFacts(
            stage=value.stage,
            component=value.component,
            reason=value.reason,
            exit_code=value.exit_code if value.HasField("exit_code") else None,
            health_status=value.health_status if value.HasField("health_status") else None,
            oom_killed=value.oom_killed if value.HasField("oom_killed") else None,
            health_exit_code=value.health_exit_code if value.HasField("health_exit_code") else None,
        )
    )


def decode_operation(value: pb.Operation) -> OperationWire:
    result = OperationWire(
        operation_uuid=UUID(value.operation_uuid),
        sequence=value.sequence,
        phase=value.phase,
        error=value.error if value.HasField("error") else None,
    )
    if value.HasField("diagnostic"):
        return result.model_copy(update={"diagnostic": decode_diagnostic(value.diagnostic)})
    return result


def _encode_inventory(payload: InventoryWire) -> pb.Inventory:
    return pb.Inventory(
        node_uuid=str(payload.node_uuid),
        enabled=payload.enabled,
        sequence=payload.sequence,
        event_cursor=payload.event_cursor,
        items=[
            pb.ObservedModule(
                placement_uuid=str(item.placement_uuid),
                fingerprint=item.fingerprint,
                running=item.running,
                ready=item.ready,
                limits=pb.Limits(
                    memory_bytes=item.limits.memory_bytes,
                    cpu_millis=item.limits.cpu_millis,
                    pids=item.limits.pids,
                ),
            )
            for item in payload.items
        ],
    )


def encode_reply(command: ControlCommand, envelope: NodeReplyWire) -> pb.SignedReply:
    proof = envelope.proof
    result = pb.SignedReply(
        proof=pb.ReplyProof(
            node_uuid=str(proof.node_uuid),
            operation_uuid=str(proof.operation_uuid),
            request_digest=bytes.fromhex(proof.request_digest),
            response_digest=bytes.fromhex(proof.response_digest),
            status_code=proof.status_code,
            issued_at=proof.issued_at,
            expires_at=proof.expires_at,
        ),
        signature=base64.b64decode(envelope.signature, validate=True),
    )
    payload = envelope.result
    if isinstance(payload, FailureWire):
        result.failure.CopyFrom(pb.Failure(code=payload.error.code))
    elif command.action == "observe_browser" and isinstance(payload, BrowserObservationWire):
        result.browser_observation.CopyFrom(encode_observation(payload))
    elif command.action == "inventory" and isinstance(payload, InventoryWire):
        result.inventory.CopyFrom(_encode_inventory(payload))
    elif command.action == "configure" and isinstance(payload, ConfigurationWire):
        result.configuration.CopyFrom(
            pb.Configuration(
                node_uuid=str(payload.node_uuid), enabled=payload.enabled, sequence=payload.sequence
            )
        )
    elif command.action in {"apply", "status"} and isinstance(payload, OperationWire):
        result.operation.CopyFrom(encode_operation(payload))
    else:
        raise ValueError("Node reply does not match the requested action")
    return result


def _decode_observed_module(value: pb.ObservedModule) -> ObservedModuleWire:
    checked = limits(value.limits)
    return ObservedModuleWire(
        placement_uuid=UUID(value.placement_uuid),
        fingerprint=value.fingerprint,
        running=value.running,
        ready=value.ready,
        limits=checked,
    )


def decode_reply(value: pb.SignedReply) -> NodeReplyWire:
    known(value)
    proof = ReplyProof(
        node_uuid=UUID(value.proof.node_uuid),
        operation_uuid=UUID(value.proof.operation_uuid),
        status_code=value.proof.status_code,
        issued_at=value.proof.issued_at,
        expires_at=value.proof.expires_at,
        request_digest=value.proof.request_digest.hex(),
        response_digest=value.proof.response_digest.hex(),
    )
    kind = value.WhichOneof("result")
    payload: ReplyPayload
    if kind == "failure":
        payload = FailureWire(error=FailureCodeWire(code=value.failure.code))
    elif kind == "browser_observation":
        payload = decode_observation(value.browser_observation)
    elif kind == "configuration":
        payload = ConfigurationWire(
            node_uuid=UUID(value.configuration.node_uuid),
            enabled=value.configuration.enabled,
            sequence=value.configuration.sequence,
        )
    elif kind == "inventory":
        inventory = value.inventory
        payload = InventoryWire(
            node_uuid=UUID(inventory.node_uuid),
            enabled=inventory.enabled,
            sequence=inventory.sequence,
            event_cursor=inventory.event_cursor,
            items=tuple(_decode_observed_module(item) for item in inventory.items),
        )
    elif kind == "operation":
        payload = decode_operation(value.operation)
    else:
        raise ValueError("Typed node reply required")
    return NodeReplyWire(
        proof=proof, signature=base64.b64encode(value.signature).decode(), result=payload
    )
