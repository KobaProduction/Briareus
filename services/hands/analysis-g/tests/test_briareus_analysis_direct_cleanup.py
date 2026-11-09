from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from briareus_analysis_g.settings import AnalysisSettings
from briareus_analysis_g.workspace_transfer import AnalysisWorkspaceTransfers
from briareus_workspace.workspace_store import WorkspaceFileStore


class DirectCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploader_removes_its_own_staged_file_after_native_import(self) -> None:
        requests: list[httpx.Request] = []
        remote_path = "/artifacts/.koba-direct/" + "a" * 32 + "-sample.bin"

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"path": remote_path})
            return httpx.Response(200, json={"success": True, "deleted": True})

        original_client = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceFileStore(Path(directory))
            (Path(directory) / "sample.bin").write_bytes(b"artifact")
            transfers = AnalysisWorkspaceTransfers(
                AnalysisSettings(direct_upload_url="http://uploader/internal/artifacts/upload"),
                workspace,
                max_file_bytes=1024,
            )
            with (
                patch.object(transfers, "_call", new=AsyncMock(return_value={"imported": True})),
                patch(
                    "briareus_analysis_g.workspace_transfer.httpx.AsyncClient",
                    side_effect=lambda **kwargs: original_client(
                        transport=httpx.MockTransport(respond), **kwargs
                    ),
                ),
            ):
                result = await transfers.import_workspace_file("project", "sample.bin")
        self.assertEqual(result["transfer_cleanup_error"], "")
        self.assertEqual([request.method for request in requests], ["POST", "DELETE"])
        self.assertEqual(requests[-1].url.params["path"], remote_path)
        self.assertEqual(requests[-1].url.params["project_id"], "project")
        self.assertEqual(requests[-1].headers["X-Koba-Proxy-Origin"], "analysis")
