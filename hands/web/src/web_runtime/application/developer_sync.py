"""Record the actual native observation even when some extension effects failed."""

from dataclasses import dataclass
from typing import Protocol

from web_runtime.domain.developer_sync import ExtensionSyncReport


class ManagedExtensionState(Protocol):
    def managed_extension_ids(self) -> frozenset[str]: ...
    def replace_managed_extension_ids(self, values: frozenset[str]) -> None: ...


@dataclass(frozen=True)
class ReconcileDeveloperSync:
    state: ManagedExtensionState

    def execute(self, report: ExtensionSyncReport, requested: tuple[str, ...] | None) -> int:
        updated = report.managed_after(self.state.managed_extension_ids(), requested)
        self.state.replace_managed_extension_ids(updated)
        report.require_success()
        return len(report.eligible_ids)
