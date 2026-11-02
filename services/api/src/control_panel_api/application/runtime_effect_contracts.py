"""Existing human runtime wire commands and named successful results."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from runtime_peer.hand_command_wire import HandCommandHeader
from runtime_peer.runtime_arguments import RuntimeArguments, runtime_arguments
from runtime_peer.tool_argument_decoding import selected_tool

RuntimeHand = Literal["terminal", "files", "web"]


class TerminalCommand(HandCommandHeader):
    arguments: RuntimeArguments

    @field_validator("arguments", mode="before")
    @classmethod
    def parse_arguments(cls, value: object, info: ValidationInfo[object]) -> RuntimeArguments:
        return runtime_arguments(selected_tool(info), value)


class RuntimePermit(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    permit: str = Field(min_length=1, repr=False)


@dataclass(frozen=True, slots=True)
class RuntimeToolOutcome[Reply]:
    result: Reply
    failed: bool


class RuntimeEffectResult[Reply](BaseModel):
    operation_uuid: UUID
    result: Reply
