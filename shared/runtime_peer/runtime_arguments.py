"""Validate private human runtime tool arguments at the caller's transport boundary."""

from pydantic import BaseModel, ConfigDict, Field

from .file_arguments import FILE_ARGUMENTS, FileArguments
from .terminal_arguments import TERMINAL_ARGUMENTS, TerminalArguments
from .tool_argument_decoding import decode_tool_arguments


class PrivateBrowserOpenArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    url: str = Field(max_length=2048)


type RuntimeArguments = TerminalArguments | FileArguments | PrivateBrowserOpenArguments

_ARGUMENTS: dict[str, type[RuntimeArguments]] = {
    **TERMINAL_ARGUMENTS,
    **FILE_ARGUMENTS,
    "browser_open": PrivateBrowserOpenArguments,
}


def runtime_arguments(tool: str, value: object) -> RuntimeArguments:
    return decode_tool_arguments(tool, value, _ARGUMENTS)
