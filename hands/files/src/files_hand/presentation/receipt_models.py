"""Map owner-owned workspace facts to the common Files response contract."""

from files_hand.application.workspace_ports import FileToolReceipt
from files_hand.application.workspace_receipts import (
    FileDirectoryPage,
    NodeFileEntry,
    NodeIngestReceipt,
)
from files_hand.application.write_chunk import ChunkWriteReceipt
from modules.files.receipts import WorkspaceHash, WorkspaceIngestReceipt
from modules.workspace_compat.domain.receipts import (
    WorkspaceAbsent,
    WorkspaceDeleted,
    WorkspaceDirectoryEntry,
    WorkspaceFileEntry,
    WorkspaceRead,
    WorkspaceStatus,
)
from runtime_peer.file_receipts import (
    FileDeleteReceipt,
    FileDirectoryReceipt,
    FileEntryReceipt,
    FileHashReceipt,
    FileIngestReceipt,
    FileReadReceipt,
    FilesReceipt,
    FileStatusReceipt,
    FileWriteReceipt,
)

_RECEIPTS: dict[type[FileToolReceipt], type[FilesReceipt]] = {
    WorkspaceStatus: FileStatusReceipt,
    FileDirectoryPage: FileDirectoryReceipt,
    NodeFileEntry: FileEntryReceipt,
    WorkspaceFileEntry: FileEntryReceipt,
    WorkspaceDirectoryEntry: FileEntryReceipt,
    WorkspaceRead: FileReadReceipt,
    WorkspaceHash: FileHashReceipt,
    ChunkWriteReceipt: FileWriteReceipt,
    WorkspaceIngestReceipt: FileIngestReceipt,
    NodeIngestReceipt: FileIngestReceipt,
    WorkspaceDeleted: FileDeleteReceipt,
    WorkspaceAbsent: FileDeleteReceipt,
}


def file_receipt(result: FileToolReceipt) -> FilesReceipt:
    try:
        model = _RECEIPTS[type(result)]
    except KeyError:
        raise ValueError("Known Files owner receipt required") from None
    return model.model_validate(result, from_attributes=True)
