"""Existing private Files records, specialized for this owner's entry models."""

from files_hand.application.workspace_receipts import FileEntry
from runtime_peer.private_file_receipts import PrivateFileEntry as PrivateFileEntry
from runtime_peer.private_file_receipts import PrivateFileHash as PrivateFileHash
from runtime_peer.private_file_receipts import PrivateFileList as SharedPrivateFileList
from runtime_peer.private_file_receipts import PrivateFileRead as PrivateFileRead

type BasicFileEntry = PrivateFileEntry | FileEntry

PrivateFileList = SharedPrivateFileList[BasicFileEntry]

type PrivateFileResult = BasicFileEntry | PrivateFileList | PrivateFileRead | PrivateFileHash
