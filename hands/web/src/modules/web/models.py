from __future__ import annotations

from dataclasses import dataclass

from modules.workspace_compat.domain.receipts import WorkspaceEntry


@dataclass(frozen=True, slots=True)
class BrowserDownload:
    file: WorkspaceEntry
    suggested_filename: str
