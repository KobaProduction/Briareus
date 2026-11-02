"""Exact Files tool argument records, independent of workspace storage implementations."""

from pydantic import BaseModel, ConfigDict
from pydantic_core import MISSING


class FileArgumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FileStatusArguments(FileArgumentRecord):
    """file_status has no argument fields."""


class FilePathArguments(FileArgumentRecord):
    path: str


class FileListArguments(FileArgumentRecord):
    path: str | MISSING = MISSING
    offset: int | MISSING = MISSING
    limit: int | MISSING = MISSING


class FileReadArguments(FilePathArguments):
    offset: int | MISSING = MISSING
    length: int | MISSING = MISSING


class FileWriteTextArguments(FilePathArguments):
    content: str
    overwrite: bool | MISSING = MISSING
    create_parents: bool | MISSING = MISSING


class FileWriteArguments(FilePathArguments):
    data_base64: str
    offset: int | MISSING = MISSING
    truncate: bool | MISSING = MISSING
    create_parents: bool | MISSING = MISSING


class FileAttachment(FileArgumentRecord):
    download_url: str
    file_id: str | MISSING | None = MISSING
    mime_type: str | MISSING | None = MISSING
    file_name: str | MISSING | None = MISSING


class FileIngestArguments(FileArgumentRecord):
    file: FileAttachment
    destination: str
    expected_size: int | MISSING | None = MISSING
    expected_sha256: str | MISSING = MISSING
    overwrite: bool | MISSING = MISSING


class FileDirectoryArguments(FilePathArguments):
    parents: bool | MISSING = MISSING


class FileTransferArguments(FileArgumentRecord):
    source: str
    destination: str
    overwrite: bool | MISSING = MISSING


class FileDeleteArguments(FilePathArguments):
    recursive: bool | MISSING = MISSING


type FileArguments = (
    FileReadArguments
    | FileWriteTextArguments
    | FileWriteArguments
    | FileDirectoryArguments
    | FileDeleteArguments
    | FilePathArguments
    | FileListArguments
    | FileIngestArguments
    | FileTransferArguments
    | FileStatusArguments
)

FILE_ARGUMENTS: dict[str, type[FileArguments]] = {
    "file_status": FileStatusArguments,
    "file_list": FileListArguments,
    "file_info": FilePathArguments,
    "file_read": FileReadArguments,
    "file_hash": FilePathArguments,
    "file_write_text": FileWriteTextArguments,
    "file_write": FileWriteArguments,
    "file_ingest": FileIngestArguments,
    "file_mkdir": FileDirectoryArguments,
    "file_copy": FileTransferArguments,
    "file_move": FileTransferArguments,
    "file_delete": FileDeleteArguments,
}
