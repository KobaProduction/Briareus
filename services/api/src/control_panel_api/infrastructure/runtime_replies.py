"""Private runtime reply bindings and explicit legacy flag-presence metadata."""

from dataclasses import dataclass

from mcp_types import CallToolResult

from control_panel_api.application.runtime_effect_contracts import RuntimeToolOutcome
from runtime_peer.browser_receipts import BrowserInspectionResult
from runtime_peer.file_receipts import FileEntryReceipt
from runtime_peer.private_file_receipts import (
    PrivateFileEntry,
    PrivateFileHash,
    PrivateFileList,
    PrivateFileRead,
)

type NativePrivateFileEntry = PrivateFileEntry | FileEntryReceipt
type NativePrivateFileReply = (
    NativePrivateFileEntry
    | PrivateFileList[NativePrivateFileEntry]
    | PrivateFileRead
    | PrivateFileHash
)


@dataclass(frozen=True, slots=True)
class LegacyRuntimeReply:
    sdk: CallToolResult
    is_error: bool
    camel_error_present: bool


type NativeRuntimeReply = (
    CallToolResult | LegacyRuntimeReply | NativePrivateFileReply | BrowserInspectionResult
)
type NativeRuntimeOutcome = RuntimeToolOutcome[NativeRuntimeReply]
