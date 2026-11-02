"""Private browser ledger codec; preserve existing reservations and atomic receipts."""

import asyncio
import json
import os
from pathlib import Path

from runtime_peer import canonical_json
from service_runtime._runtime_reference_bindings import _PrivateRootBinding
from web_hand.application.execute_private import StoredBrowserOperation
from web_hand.domain.private_effect import PrivateBrowserOperation
from web_hand.runtime_views import BrowserCallReceipt, RuntimeOperationLedger


class FileBrowserHistory(_PrivateRootBinding):
    def _path(self, operation: PrivateBrowserOperation) -> Path:
        return self._root / (str(operation.operation_uuid) + ".json")

    async def load(
        self, operation: PrivateBrowserOperation
    ) -> StoredBrowserOperation[BrowserCallReceipt] | None:
        return await asyncio.to_thread(self._load, operation)

    def _load(
        self, operation: PrivateBrowserOperation
    ) -> StoredBrowserOperation[BrowserCallReceipt] | None:
        target = self._path(operation)
        if not target.exists():
            return None
        saved = RuntimeOperationLedger.model_validate_json(target.read_bytes())
        return StoredBrowserOperation(saved.fingerprint, saved.reply)

    async def reserve(self, operation: PrivateBrowserOperation) -> None:
        await asyncio.to_thread(self._reserve, operation)

    def _reserve(self, operation: PrivateBrowserOperation) -> None:
        if len(list(self._root.glob("*.json"))) >= 10000:
            raise ValueError("Browser history capacity reached")
        target = self._path(operation)
        with target.open("x") as pending:
            os.chmod(target, 0o600)
            json.dump(
                RuntimeOperationLedger(fingerprint=operation.fingerprint).model_dump(
                    mode="json", exclude_unset=True
                ),
                pending,
            )
            pending.flush()
            os.fsync(pending.fileno())

    async def complete(self, operation: PrivateBrowserOperation, reply: BrowserCallReceipt) -> None:
        await asyncio.to_thread(self._complete, operation, reply)

    def _complete(self, operation: PrivateBrowserOperation, reply: BrowserCallReceipt) -> None:
        encoded = canonical_json(
            RuntimeOperationLedger(fingerprint=operation.fingerprint, reply=reply).model_dump(
                mode="json", exclude_unset=True
            )
        )
        if len(encoded) > 262144:
            raise ValueError("Browser output budget exceeded")
        target = self._path(operation)
        temporary = target.with_suffix(".pending")
        with temporary.open("xb") as completed:
            os.chmod(temporary, 0o600)
            completed.write(encoded)
            completed.flush()
            os.fsync(completed.fileno())
        temporary.replace(target)
