"""Version-pinned owner journal documents validated at the private transport boundary."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)

from control_panel_api.domain.owner_events import (
    MAX_MCP_CALL_DURATION_MS,
    MCP_TOOL_PATTERN,
    GatewayCallStatus,
    McpCall,
    McpHand,
    McpOwnerEvent,
    OwnerEvent,
    RuntimePolicyTarget,
)


def identifier(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError("Invalid owner event identifier")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("Invalid owner event identifier")
    return parsed


type CanonicalUUID = Annotated[UUID, BeforeValidator(identifier)]


class OwnerEventWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: CanonicalUUID
    type: StrictStr
    occurredAt: StrictStr
    actor_id: CanonicalUUID | None
    project_id: CanonicalUUID | None
    operation_id: CanonicalUUID | None
    entity_id: UUID | RuntimePolicyTarget | None

    @field_validator("entity_id", mode="before")
    @classmethod
    def entity_selector(cls, value: object) -> UUID | RuntimePolicyTarget | None:
        if isinstance(value, RuntimePolicyTarget):
            return value
        if value == "server":
            return RuntimePolicyTarget()
        if isinstance(value, str) and value.startswith("node:"):
            return RuntimePolicyTarget(identifier(value[5:]))
        return None if value is None else identifier(value)

    @model_validator(mode="after")
    def valid_owner_event(self) -> Self:
        self.domain()
        return self

    @field_serializer("entity_id")
    def wire_selector(self, value: UUID | RuntimePolicyTarget | None) -> UUID | str | None:
        return value.selector if isinstance(value, RuntimePolicyTarget) else value

    def domain(self) -> OwnerEvent:
        return OwnerEvent(
            self.event_id,
            self.type,
            self.occurredAt,
            self.actor_id,
            self.project_id,
            self.operation_id,
            self.entity_id,
        )


class McpCallWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hand: McpHand
    tool: str = Field(pattern=f"^{MCP_TOOL_PATTERN}$")
    status: GatewayCallStatus
    session_uuid: CanonicalUUID | None
    node_uuid: CanonicalUUID
    placement_uuid: CanonicalUUID
    duration_ms: int = Field(strict=True, ge=0, le=MAX_MCP_CALL_DURATION_MS)
    transport: Literal["gateway-mcp"]

    def to_call(self) -> McpCall:
        return McpCall(
            self.hand,
            self.tool,
            self.status,
            self.session_uuid,
            self.node_uuid,
            self.placement_uuid,
            self.duration_ms,
        )


class McpOwnerEventWire(OwnerEventWire):
    call: McpCallWire

    def domain(self) -> McpOwnerEvent:
        return McpOwnerEvent(
            self.event_id,
            self.type,
            self.occurredAt,
            self.actor_id,
            self.project_id,
            self.operation_id,
            self.entity_id,
            self.call.to_call(),
        )
