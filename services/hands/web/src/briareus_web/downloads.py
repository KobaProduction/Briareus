"""Persist browser downloads once into the shared Server workspace."""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from briareus_workspace.workspace_store import WorkspaceFileStore

if TYPE_CHECKING:
    from playwright.async_api import Download


class BrowserDownloadError(RuntimeError):
    """A browser download could not be persisted into the Server workspace."""


class BrowserDownloadStore:
    def __init__(self, workspace: WorkspaceFileStore) -> None:
        self.workspace = workspace
        self._pending: WeakKeyDictionary[Download, asyncio.Task[Path]] = WeakKeyDictionary()
        self._completed: WeakKeyDictionary[Download, Path] = WeakKeyDictionary()
        self._failed: WeakKeyDictionary[Download, str] = WeakKeyDictionary()
        self._active: set[asyncio.Task[Path]] = set()

    @staticmethod
    def _filename(value: str) -> str:
        name = value.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(
            "_" if ord(character) < 32 or character in '<>:"/\\|?*\x7f' else character
            for character in name
        ).strip(" .")
        return name.encode("utf-8")[:200].decode("utf-8", errors="ignore") or "download"

    async def _persist(self, download: Download) -> Path:
        directory: Path = self.workspace.target_path("browser/downloads")
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        filename = self._filename(download.suggested_filename)
        partial = directory / (".incoming-" + uuid.uuid4().hex)
        try:
            await download.save_as(str(partial))
            destination = directory / filename
            while True:
                try:
                    # Publishing a completed inode is atomic and never replaces another file.
                    os.link(partial, destination)
                except FileExistsError:
                    stem, suffix = Path(filename).stem, Path(filename).suffix
                    destination = directory / f"{stem}-{uuid.uuid4().hex[:10]}{suffix}"
                else:
                    with contextlib.suppress(Exception):
                        await download.delete()
                    return destination
        finally:
            partial.unlink(missing_ok=True)

    def schedule(self, download: Download) -> None:
        if download in self._pending or download in self._completed or download in self._failed:
            return
        task = asyncio.create_task(self._persist(download))
        self._pending[download] = task
        self._active.add(task)

        def completed(job: asyncio.Task[Path]) -> None:
            self._active.discard(job)
            self._pending.pop(download, None)
            try:
                self._completed[download] = job.result()
            except asyncio.CancelledError:
                self._failed[download] = "Browser download was interrupted by disconnect"
            except Exception:
                # Consume background errors without exporting downloaded contents or URLs.
                self._failed[download] = "Browser download could not be saved to Server workspace"

        task.add_done_callback(completed)

    async def saved(self, download: Download) -> Path:
        if download in self._failed:
            raise BrowserDownloadError(self._failed[download])
        if download in self._completed:
            return self._completed[download]
        self.schedule(download)
        try:
            return await asyncio.shield(self._pending[download])
        except Exception as error:
            raise BrowserDownloadError(
                "Browser download could not be saved to Server workspace"
            ) from error

    async def disconnect(self) -> None:
        if not self._active:
            return
        _done, pending = await asyncio.wait(tuple(self._active), timeout=5)
        for task in pending:
            task.cancel()
        if pending:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*pending, return_exceptions=True)
