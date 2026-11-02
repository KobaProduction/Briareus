"""Supervisor-private durable receipt files, preserving the existing format."""

import json
import os
from pathlib import Path

from pydantic_core import MISSING

from service_runtime._runtime_reference_bindings import _PrivateRootBinding
from terminal_hand.application.execute_operation import StoredOperation
from terminal_hand.domain.operation import OperationIdentity, require_history_capacity
from terminal_hand.infrastructure.worker_messages import SavedOperation, TerminalReply


class FileOperationHistory(_PrivateRootBinding):
    def _path(self, identity: OperationIdentity) -> Path:
        return self._root / (str(identity.operation_uuid) + ".json")

    def load(self, identity: OperationIdentity) -> StoredOperation[TerminalReply] | None:
        target = self._path(identity)
        if not target.exists():
            return None
        previous = SavedOperation.model_validate_json(target.read_bytes())
        reply = previous.result if previous.result is not MISSING else None
        return StoredOperation(previous.fingerprint, reply)

    def reserve(self, identity: OperationIdentity) -> None:
        require_history_capacity(len(list(self._root.glob("*.json"))))
        with self._path(identity).open("x") as pending:
            os.chmod(pending.name, 0o600)
            json.dump(
                SavedOperation(fingerprint=identity.fingerprint).model_dump(mode="json"), pending
            )
            pending.flush()
            os.fsync(pending.fileno())

    def complete(self, identity: OperationIdentity, reply: TerminalReply) -> None:
        target = self._path(identity)
        temporary = target.with_suffix(".pending")
        with temporary.open("x") as completed:
            os.chmod(temporary, 0o600)
            json.dump(
                SavedOperation(fingerprint=identity.fingerprint, result=reply).model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                ),
                completed,
            )
            completed.flush()
            os.fsync(completed.fileno())
        temporary.replace(target)
