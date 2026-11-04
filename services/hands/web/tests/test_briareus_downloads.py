from __future__ import annotations

import asyncio
import gc
import tempfile
import unittest
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, patch

from briareus_web.browser import BrowserError, BrowserManager
from briareus_web.downloads import BrowserDownloadError, BrowserDownloadStore
from briareus_workspace.workspace_store import WorkspaceFileStore

if TYPE_CHECKING:
    from playwright.async_api import Download, Page


class FakeDownload:
    def __init__(self, filename: str = "sample.txt", *, failure: bool = False) -> None:
        self.suggested_filename = filename
        self.save_calls = 0
        self.delete_calls = 0
        self.failure = failure

    async def save_as(self, destination: str) -> None:
        self.save_calls += 1
        await asyncio.sleep(0)
        if self.failure:
            raise OSError("secret URL must not reach background diagnostics")
        await asyncio.to_thread(Path(destination).write_bytes, b"download payload")

    async def delete(self) -> None:
        self.delete_calls += 1


class DownloadInfo:
    def __init__(self, download: FakeDownload) -> None:
        self.value: asyncio.Future[Download] = asyncio.get_running_loop().create_future()
        self.value.set_result(cast("Download", download))

    async def __aenter__(self) -> DownloadInfo:
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        pass


class DownloadPage:
    def __init__(self, download: FakeDownload) -> None:
        self.download = download
        self.callbacks: list[Callable[[Download], None]] = []
        self.clicks = 0

    def on(self, event: str, callback: Callable[[Download], None]) -> None:
        if event == "download":
            self.callbacks.append(callback)

    def expect_download(self) -> DownloadInfo:
        return DownloadInfo(self.download)

    async def click(self) -> None:
        self.clicks += 1
        for callback in self.callbacks:
            callback(cast("Download", self.download))
        await asyncio.sleep(0)


def manager(root: Path) -> BrowserManager:
    return BrowserManager(
        workspace=WorkspaceFileStore(root),
        cdp_url="http://chromium:9222",
        control_url="http://chromium:9001/RPC2",
        control_token="download-test",
        profile_dir=root.parent / "browser-profile",
        executable_path="/usr/bin/chromium",
        headless=True,
        timeout_ms=1000,
        viewport_width=1200,
        viewport_height=800,
        max_snapshot_text_chars=1000,
        max_snapshot_elements=50,
    )


class BrowserDownloadContracts(unittest.IsolatedAsyncioTestCase):
    async def test_operator_click_is_saved_without_calling_the_download_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            browser = manager(Path(directory))
            download = FakeDownload()
            page = DownloadPage(download)
            browser._register_page(cast("Page", page))
            browser._register_page(cast("Page", page))
            self.assertEqual(len(page.callbacks), 1)
            await page.click()
            await browser._downloads.disconnect()
            self.assertEqual(
                (Path(directory) / "browser/downloads/sample.txt").read_bytes(), b"download payload"
            )
            self.assertEqual(download.save_calls, 1)
            self.assertEqual(download.delete_calls, 1)

    async def test_mcp_awaits_the_passive_save_and_moves_the_same_file_to_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = manager(root)
            download = FakeDownload()
            page = DownloadPage(download)
            browser._register_page(cast("Page", page))
            with patch.object(browser, "_locator", AsyncMock(return_value=(page, page))):
                result = await browser.download("page", "ref", "projects/result.txt")
            self.assertEqual(result["path"], "projects/result.txt")
            self.assertEqual((root / "projects/result.txt").read_bytes(), b"download payload")
            self.assertEqual(list((root / "browser/downloads").iterdir()), [])
            self.assertEqual(download.save_calls, 1)
            self.assertEqual(download.delete_calls, 1)

    async def test_default_download_destination_is_shared_server_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            browser = manager(Path(directory))
            download = FakeDownload()
            page = DownloadPage(download)
            browser._register_page(cast("Page", page))
            with patch.object(browser, "_locator", AsyncMock(return_value=(page, page))):
                result = await browser.download("page", "ref")
            self.assertEqual(result["path"], "browser/downloads/sample.txt")
            self.assertEqual(download.save_calls, 1)
            self.assertEqual(download.delete_calls, 1)

    async def test_existing_explicit_destination_is_rejected_before_click(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.txt").write_text("keep", encoding="utf-8")
            browser = manager(root)
            page = DownloadPage(FakeDownload())
            with (
                patch.object(browser, "_locator", AsyncMock(return_value=(page, page))),
                self.assertRaises(BrowserError),
            ):
                await browser.download("page", "ref", "existing.txt")
            self.assertEqual(page.clicks, 0)
            self.assertEqual((root / "existing.txt").read_text(), "keep")

    async def test_existing_default_filename_and_traversal_names_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = BrowserDownloadStore(WorkspaceFileStore(root))
            destination = root / "browser/downloads/sample.txt"
            destination.parent.mkdir(parents=True)
            destination.write_text("keep", encoding="utf-8")
            download = FakeDownload("../../sample.txt")
            saved = await store.saved(cast("Download", download))
            self.assertEqual(saved.parent, destination.parent)
            self.assertNotEqual(saved, destination)
            self.assertEqual(destination.read_text(), "keep")
            self.assertEqual(saved.read_bytes(), b"download payload")
            self.assertEqual(list(destination.parent.glob(".incoming-*")), [])

    async def test_completed_jobs_release_tasks_and_download_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = BrowserDownloadStore(WorkspaceFileStore(Path(directory)))
            download = FakeDownload()
            reference = weakref.ref(download)
            first = await store.saved(cast("Download", download))
            await asyncio.sleep(0)
            self.assertEqual(await store.saved(cast("Download", download)), first)
            self.assertEqual(download.save_calls, 1)
            self.assertEqual(download.delete_calls, 1)
            self.assertEqual(len(store._pending), 0)
            self.assertEqual(len(store._active), 0)
            del download
            gc.collect()
            self.assertIsNone(reference())
            self.assertEqual(len(store._completed), 0)

    async def test_background_failure_is_consumed_without_leaking_original_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = BrowserDownloadStore(WorkspaceFileStore(Path(directory)))
            download = FakeDownload(failure=True)
            store.schedule(cast("Download", download))
            await store.disconnect()
            with self.assertRaises(BrowserDownloadError) as failure:
                await store.saved(cast("Download", download))
            self.assertNotIn("secret URL", str(failure.exception))
            self.assertEqual(len(store._active), 0)
            self.assertEqual(len(store._pending), 0)
            root = Path(directory)
            partials = await asyncio.to_thread(lambda: list(root.rglob(".incoming-*")))
            self.assertEqual(partials, [])
