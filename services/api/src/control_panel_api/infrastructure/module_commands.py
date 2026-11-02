"""Transport command schemas bound to the concrete argument record of each tool."""

from pydantic import Field, ValidationInfo, field_validator

from runtime_peer.analysis_arguments import ANALYSIS_ARGUMENTS, AnalysisArguments
from runtime_peer.browser_arguments import WEB_ARGUMENTS, WebArguments
from runtime_peer.file_arguments import FILE_ARGUMENTS, FileArguments
from runtime_peer.hand_command_wire import ProjectCommandHeader
from runtime_peer.terminal_arguments import TERMINAL_ARGUMENTS, TerminalArguments
from runtime_peer.tool_argument_decoding import decode_tool_arguments, selected_tool


class HumanCommandHeader(ProjectCommandHeader):
    @property
    def preparation_engine(self) -> str | None:
        return None


class TerminalToolCommand(HumanCommandHeader):
    arguments: TerminalArguments = Field(default_factory=dict, validate_default=True)

    @field_validator("arguments", mode="before")
    @classmethod
    def tool_arguments(cls, value: object, info: ValidationInfo[object]) -> TerminalArguments:
        return decode_tool_arguments(selected_tool(info), value, TERMINAL_ARGUMENTS)


class FilesToolCommand(HumanCommandHeader):
    arguments: FileArguments = Field(default_factory=dict, validate_default=True)

    @field_validator("arguments", mode="before")
    @classmethod
    def tool_arguments(cls, value: object, info: ValidationInfo[object]) -> FileArguments:
        return decode_tool_arguments(selected_tool(info), value, FILE_ARGUMENTS)


class BrowserToolCommand(HumanCommandHeader):
    arguments: WebArguments = Field(default_factory=dict, validate_default=True)

    @field_validator("arguments", mode="before")
    @classmethod
    def tool_arguments(cls, value: object, info: ValidationInfo[object]) -> WebArguments:
        return decode_tool_arguments(selected_tool(info), value, WEB_ARGUMENTS)


class AnalysisToolCommand(HumanCommandHeader):
    arguments: AnalysisArguments = Field(default_factory=dict, validate_default=True)

    @field_validator("arguments", mode="before")
    @classmethod
    def tool_arguments(cls, value: object, info: ValidationInfo[object]) -> AnalysisArguments:
        return decode_tool_arguments(selected_tool(info), value, ANALYSIS_ARGUMENTS)

    @property
    def preparation_engine(self) -> str | None:
        return self.arguments.preparation_engine


type NativeToolCommand = (
    TerminalToolCommand | FilesToolCommand | BrowserToolCommand | AnalysisToolCommand
)

MODULE_COMMANDS: dict[str, type[NativeToolCommand]] = {
    "terminal": TerminalToolCommand,
    "files": FilesToolCommand,
    "web": BrowserToolCommand,
    "reverse": AnalysisToolCommand,
}
