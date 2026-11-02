"""Prepare an immutable, integrity-checked binary for a fixed native query."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from radare2_hand.domain.binaries import BinaryManifest
from radare2_hand.domain.commands import NativeCommand


@dataclass(frozen=True, slots=True)
class NativeBinary:
    path: str
    metadata: BinaryManifest
    data: bytes


class NativeStorage(Protocol):
    def load(self, binary_id: UUID) -> NativeBinary: ...


@dataclass(frozen=True, slots=True)
class PreparedInspection:
    command: NativeCommand
    path: str


class InspectBinary:
    def __init__(self, storage: NativeStorage) -> None:
        self.storage = storage

    def prepare(self, command: NativeCommand) -> PreparedInspection:
        binary = self.storage.load(command.binary_id)
        binary.metadata.require_integrity(binary.data, stored=True)
        return PreparedInspection(command, binary.path)
