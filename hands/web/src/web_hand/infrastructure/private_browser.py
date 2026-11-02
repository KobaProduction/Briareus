"""Disposable BrowserManager adapter, bounded by the original private effect lease."""

import asyncio
import tempfile
import time
from pathlib import Path

from modules.web.browser import BrowserManager
from modules.workspace_compat.legacy_store import WorkspaceFileStore
from service_runtime._runtime_reference_bindings import _PrivateRootBinding
from web_hand.domain.private_effect import PrivateBrowserOperation
from web_hand.runtime_views import BrowserCallReceipt, BrowserInspectionResult


class DisposablePrivateBrowser(_PrivateRootBinding):
    now = staticmethod(time.time)

    @staticmethod
    def _browser(work: Path) -> BrowserManager:
        return BrowserManager(
            workspace=WorkspaceFileStore(work / "workspace"),
            profile_dir=work / "profile",
            executable_path="/usr/bin/chromium",
            headless=True,
            xvfb_enabled=False,
            timeout_ms=8000,
            viewport_width=1280,
            viewport_height=800,
            max_snapshot_text_chars=16000,
            max_snapshot_elements=100,
            chromium_args=(
                "--proxy-server=http://web-egress:8080",
                "--proxy-bypass-list=<-loopback>",
                "--disable-quic",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE web-egress",
            ),
        )

    async def inspect(self, operation: PrivateBrowserOperation) -> BrowserCallReceipt:
        with tempfile.TemporaryDirectory(prefix="invocation-", dir=self._root) as work:
            browser = self._browser(Path(work))
            try:
                async with asyncio.timeout(min(16, max(0, operation.expires_at - self.now()))):
                    page = await browser.open(operation.url)
                    snapshot = await browser.snapshot(page.page_id)
                    result = BrowserInspectionResult(page=page, snapshot=snapshot)
            finally:
                await browser._stop_runtime(stop_display=True)
        return BrowserCallReceipt(operation_uuid=operation.operation_uuid, result=result)
