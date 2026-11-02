"""Concrete node reply models at the signed protobuf/JSON boundary."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .browser_observation import (
    BrowserObservationSelector,
    BrowserObservationWire,
    BrowserObservedFrameWire,
)
from .control import ReplyProof
from .diagnostics import FailureDiagnostic, diagnostic_facts, diagnostic_payload
from .domain.browser_observation import NodeBrowserObservation
from .domain.observations import (
    NodeConfiguration,
    NodeFailure,
    NodeInventory,
    NodeOperation,
    NodeReply,
    ObservedLimits,
    ObservedModule,
)
from .models import ResourceLimits


class ReplyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ConfigurationWire(ReplyModel):
    node_uuid: UUID
    sequence: int
    enabled: bool

    def observation(self) -> NodeConfiguration:
        return NodeConfiguration(self.node_uuid, self.sequence, self.enabled)


class ObservedModuleWire(ReplyModel):
    placement_uuid: UUID
    fingerprint: str
    running: bool
    ready: bool
    limits: ResourceLimits

    def observation(self) -> ObservedModule:
        return ObservedModule(
            self.placement_uuid,
            self.fingerprint,
            self.running,
            self.ready,
            ObservedLimits(self.limits.memory_bytes, self.limits.cpu_millis, self.limits.pids),
        )


class InventoryWire(ReplyModel):
    node_uuid: UUID
    enabled: bool
    event_cursor: int
    sequence: int
    items: tuple[ObservedModuleWire, ...]

    def observation(self) -> NodeInventory:
        return NodeInventory(
            self.node_uuid,
            self.enabled,
            self.event_cursor,
            self.sequence,
            tuple(item.observation() for item in self.items),
        )


class OperationWire(ReplyModel):
    operation_uuid: UUID
    sequence: int
    phase: str
    error: str | None
    diagnostic: FailureDiagnostic | None = None

    def observation(self) -> NodeOperation:
        return NodeOperation(
            self.operation_uuid,
            self.sequence,
            self.phase,
            self.error,
            diagnostic_facts(self.diagnostic) if self.diagnostic is not None else None,
        )


class FailureCodeWire(ReplyModel):
    code: str


class FailureWire(ReplyModel):
    error: FailureCodeWire

    def observation(self) -> NodeFailure:
        return NodeFailure(self.error.code)


type ReplyPayload = (
    FailureWire | ConfigurationWire | InventoryWire | OperationWire | BrowserObservationWire
)


class NodeReplyWire(ReplyModel):
    proof: ReplyProof
    signature: str
    result: ReplyPayload


def operation_wire(value: NodeOperation) -> OperationWire:
    result = OperationWire(
        operation_uuid=value.operation_uuid,
        sequence=value.sequence,
        phase=value.phase,
        error=value.error,
    )
    if value.diagnostic is not None:
        return result.model_copy(update={"diagnostic": diagnostic_payload(value.diagnostic)})
    return result


def browser_observation_wire(value: NodeBrowserObservation) -> BrowserObservationWire:
    target = value.target
    frame = value.frame
    return BrowserObservationWire(
        target=BrowserObservationSelector(
            project_uuid=target.project_uuid,
            placement_uuid=target.placement_uuid,
            fingerprint=target.fingerprint,
            actor_uuid=target.actor_uuid,
            agent_session_uuid=target.agent_session_uuid,
            grant_revision=target.grant_revision,
        ),
        frame=BrowserObservedFrameWire(
            source_request_uuid=frame.source_request_uuid,
            captured_at=frame.captured_at,
            page_id=frame.page_id,
            url=frame.url,
            title=frame.title,
            png_base64=frame.png_base64,
        )
        if frame is not None
        else None,
    )


def reply_payload(value: NodeReply) -> ReplyPayload:
    if isinstance(value, NodeBrowserObservation):
        return browser_observation_wire(value)
    if isinstance(value, NodeFailure):
        return FailureWire(error=FailureCodeWire(code=value.code))
    if isinstance(value, NodeConfiguration):
        return ConfigurationWire(
            node_uuid=value.node_uuid, sequence=value.sequence, enabled=value.enabled
        )
    if isinstance(value, NodeOperation):
        return operation_wire(value)
    return InventoryWire(
        node_uuid=value.node_uuid,
        enabled=value.enabled,
        event_cursor=value.event_cursor,
        sequence=value.sequence,
        items=tuple(
            ObservedModuleWire(
                placement_uuid=item.placement_uuid,
                fingerprint=item.fingerprint,
                running=item.running,
                ready=item.ready,
                limits=ResourceLimits(
                    memory_bytes=item.limits.memory_bytes,
                    cpu_millis=item.limits.cpu_millis,
                    pids=item.limits.pids,
                ),
            )
            for item in value.items
        ),
    )
