"""Files transport projections; omission remains distinct from an explicit null."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, model_validator
from pydantic_core import MISSING


class FileReceiptRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, from_attributes=True, hide_input_in_errors=True
    )


class FilePathReceipt(FileReceiptRecord):
    path: StrictStr


class FileStatusReceipt(FileReceiptRecord):
    root: StrictStr
    free_bytes: StrictInt
    used_bytes: StrictInt
    total_bytes: StrictInt


class FileEntryReceipt(FilePathReceipt):
    name: StrictStr
    size_bytes: StrictInt
    modified_at_ns: StrictInt
    type: Literal["file", "directory"]
    mime_type: StrictStr | MISSING = MISSING

    @model_validator(mode="after")
    def directory_has_no_mime(self) -> Self:
        if self.type == "directory" and self.mime_type is not MISSING:
            raise ValueError("Directory receipts have no MIME field")
        return self


class FileDirectoryReceipt(FilePathReceipt):
    entries: tuple[FileEntryReceipt, ...]
    count: StrictInt
    total: StrictInt
    offset: StrictInt
    limit: StrictInt
    truncated: StrictBool


class FileReadReceipt(FilePathReceipt):
    offset: StrictInt
    bytes_read: StrictInt
    next_offset: StrictInt
    size_bytes: StrictInt
    eof: StrictBool
    data_base64: StrictStr


class FileHashReceipt(FilePathReceipt):
    sha256: StrictStr


class FileWriteReceipt(FilePathReceipt):
    bytes_written: StrictInt
    next_offset: StrictInt
    size_bytes: StrictInt


class FileIngestReceipt(FileEntryReceipt):
    type: Literal["file"]
    sha256: StrictStr
    completed: Literal[True]
    transport: Literal["client-file"]


class FileDeleteReceipt(FilePathReceipt):
    deleted: Literal[True] | MISSING = MISSING
    already_absent: Literal[True] | MISSING = MISSING

    @model_validator(mode="after")
    def exact_delete_outcome(self) -> Self:
        if (self.deleted is MISSING) == (self.already_absent is MISSING):
            raise ValueError("Exactly one Files deletion outcome is required")
        return self


type FilesReceipt = (
    FileIngestReceipt
    | FileDirectoryReceipt
    | FileReadReceipt
    | FileHashReceipt
    | FileWriteReceipt
    | FileDeleteReceipt
    | FileStatusReceipt
    | FileEntryReceipt
)

FILE_RESULTS: dict[str, type[FilesReceipt]] = {
    "file_status": FileStatusReceipt,
    "file_list": FileDirectoryReceipt,
    "file_info": FileEntryReceipt,
    "file_read": FileReadReceipt,
    "file_hash": FileHashReceipt,
    "file_write_text": FileEntryReceipt,
    "file_write": FileWriteReceipt,
    "file_ingest": FileIngestReceipt,
    "file_mkdir": FileEntryReceipt,
    "file_copy": FileEntryReceipt,
    "file_move": FileEntryReceipt,
    "file_delete": FileDeleteReceipt,
}
