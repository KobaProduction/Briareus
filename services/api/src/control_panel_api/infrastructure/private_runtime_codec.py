"""Decode each private owner's actual wire contract before any result is released."""

import json
from dataclasses import fields
from uuid import UUID

from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict, TypeAdapter

from control_panel_api.application.runtime_effect_contracts import RuntimeHand, RuntimeToolOutcome
from runtime_peer.browser_receipts import BrowserCallReceipt
from runtime_peer.file_receipts import FileEntryReceipt
from runtime_peer.private_file_receipts import (
    PrivateFileEntry,
    PrivateFileHash,
    PrivateFileList,
    PrivateFileRead,
)

from .module_codec import terminal_reply
from .runtime_replies import (
    LegacyRuntimeReply,
    NativePrivateFileEntry,
    NativePrivateFileReply,
    NativeRuntimeOutcome,
    NativeRuntimeReply,
)


class _TerminalOwnerReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    result: CallToolResult


class _LegacyErrorFlag(BaseModel):
    is_error: bool = False


class _OperationHeader(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    operation_uuid: UUID


_ENTRY = TypeAdapter[PrivateFileEntry](PrivateFileEntry)


def _file_entry(value: object) -> NativePrivateFileEntry:
    if not isinstance(value, dict):
        raise ValueError("Private file entry required")
    if "modified_at_ns" in value:
        return FileEntryReceipt.model_validate(value)
    if set(value) != {field.name for field in fields(PrivateFileEntry)}:
        raise ValueError("Exact private file entry fields required")
    return _ENTRY.validate_json(json.dumps(value, allow_nan=False), strict=True)


def _scalar_file_receipt[Receipt: (PrivateFileRead, PrivateFileHash)](
    value: object, model: type[Receipt]
) -> Receipt:
    if not isinstance(value, dict) or set(value) != {field.name for field in fields(model)}:
        raise ValueError("Exact private file receipt fields required")
    return TypeAdapter[Receipt](model).validate_json(
        json.dumps(value, allow_nan=False), strict=True
    )


def _file_result(value: object, tool: str) -> NativePrivateFileReply:
    if tool == "file_info":
        return _file_entry(value)
    if not isinstance(value, dict):
        raise ValueError("Private Files result required")
    if tool == "file_list":
        if (
            set(value) != {"path", "entries"}
            or not isinstance(value["path"], str)
            or not isinstance(value["entries"], list)
        ):
            raise ValueError("Exact private file inventory fields required")
        return PrivateFileList[NativePrivateFileEntry](
            value["path"], tuple(_file_entry(entry) for entry in value["entries"])
        )
    if tool == "file_read":
        return _scalar_file_receipt(value, PrivateFileRead)
    if tool == "file_hash":
        return _scalar_file_receipt(value, PrivateFileHash)
    raise ValueError("Current private Files tool required")


def decode_runtime_receipt(
    value: object, *, hand: RuntimeHand, tool: str, operation_uuid: UUID
) -> NativeRuntimeOutcome:
    if hand == "web":
        reply = BrowserCallReceipt.model_validate_json(
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
        if reply.operation_uuid != operation_uuid:
            raise ValueError("Current browser operation receipt required")
        return RuntimeToolOutcome[NativeRuntimeReply](reply.result, False)
    if not isinstance(value, dict) or "result" not in value:
        raise ValueError("Current Hand owner receipt required")
    if hand == "files":
        if set(value) != {"operation_uuid", "result"}:
            raise ValueError("Exact private Files owner receipt required")
        header = _OperationHeader.model_validate(value)
        if header.operation_uuid != operation_uuid:
            raise ValueError("Current Files operation receipt required")
        return RuntimeToolOutcome[NativeRuntimeReply](_file_result(value["result"], tool), False)
    owner = _TerminalOwnerReply.model_validate(value)
    if owner.id is not None and owner.id != operation_uuid:
        raise ValueError("Current Terminal operation receipt required")
    result = terminal_reply(owner.result, tool)
    legacy = _LegacyErrorFlag.model_validate(value["result"])
    failed = result.is_error or legacy.is_error
    raw_result = value["result"]
    if isinstance(raw_result, dict) and "is_error" in raw_result:
        compatibility = LegacyRuntimeReply(result, legacy.is_error, "isError" in raw_result)
        return RuntimeToolOutcome[NativeRuntimeReply](compatibility, failed)
    return RuntimeToolOutcome[NativeRuntimeReply](result, failed)
