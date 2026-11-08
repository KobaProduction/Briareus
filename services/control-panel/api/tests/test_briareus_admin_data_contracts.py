from __future__ import annotations

import ast
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import control_panel_api
from briareus_server.terminal.manager import TerminalManager
from briareus_server.terminal.settings import TerminalSettings
from briareus_workspace.settings import FileSettings
from control_panel_api.domain.admin_data.browser import BrowserDebugTarget
from control_panel_api.domain.admin_data.files import FileEntry, FileStats
from control_panel_api.domain.admin_data.terminal import (
    JobList,
    TerminalJob,
    TerminalStatus,
    WorkspaceList,
)
from control_panel_api.infrastructure.files import FileAdminStore
from control_panel_api.infrastructure.terminal import TerminalAdminClient
from control_panel_api.presentation.admin_routes.browser import BrowserRoutes
from control_panel_api.presentation.admin_routes.context import WebApiContext
from control_panel_api.presentation.admin_routes.terminal import TerminalRoutes
from fastapi import APIRouter, FastAPI
from pydantic import ValidationError
from starlette.testclient import TestClient


class AdminDataContracts(unittest.IsolatedAsyncioTestCase):
    def test_remote_debug_response_keeps_its_required_protocol_field(self) -> None:
        services = Mock()
        services.realtime = None
        services.web.debug_target = AsyncMock(
            return_value=BrowserDebugTarget(
                page_id="page-1",
                target_id="target-1",
                title="Example",
                url="https://example.test",
            )
        )
        context = Mock(spec=WebApiContext)
        context.mutation.return_value = services
        router = APIRouter()
        BrowserRoutes(context).register(router)
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as http:
            response = http.post("/browser/remote-debug", json={"page_id": "page-1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["protocol"], "briareus.v1")
        self.assertEqual(response.json()["websocket_path"], "/api/browser/cdp/page/target-1")

    def test_filesystem_adapter_returns_models_for_real_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FileAdminStore(FileSettings(workspace_root=Path(directory)))
            uploaded = store.upload(BytesIO(b"hello"), destination="notes.txt")
            self.assertIsInstance(uploaded, FileEntry)
            self.assertEqual((uploaded.type, uploaded.size_bytes), ("file", 5))
            listing = store.list()
            self.assertEqual(listing.entries[0], uploaded)
            stats = store.stats()
            self.assertIsInstance(stats, FileStats)
            self.assertEqual((stats.files, stats.size_bytes), (1, 5))
            self.assertTrue(store.delete("notes.txt").deleted)
            self.assertTrue(store.delete("notes.txt").already_absent)

    async def test_current_terminal_producer_fits_panel_contract_and_preserves_wire(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = TerminalManager(TerminalSettings(workspace_root=root, home=root / "home"))
            manager.workspace_create("fixture")
            status = TerminalStatus.model_validate(manager.status())
            workspaces = WorkspaceList.model_validate(manager.workspace_list())
            jobs = JobList.model_validate(manager.job_list())
            self.assertEqual(status.workspaces, 1)
            self.assertEqual(workspaces.workspaces[0].workspace_id, "fixture")
            client = TerminalAdminClient()
            with patch.object(
                client,
                "_call",
                AsyncMock(
                    side_effect=[
                        status.to_json(),
                        workspaces.to_json(),
                        jobs.to_json(),
                    ]
                ),
            ):
                overview = await client.overview()
            services = Mock()
            services.terminal.overview = AsyncMock(return_value=overview)
            context = Mock(spec=WebApiContext)
            context.available.return_value = services
            app = FastAPI()
            app.add_api_route("/terminal", TerminalRoutes(context).terminal_overview)
            with TestClient(app) as http:
                response = http.get("/terminal")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], status.to_json())
            self.assertEqual(response.json()["workspaces"], workspaces.to_json()["workspaces"])

    def test_known_fields_do_not_coerce_invalid_data_or_accept_unknown_fields(self) -> None:
        valid = {
            "path": "note",
            "name": "note",
            "type": "file",
            "size_bytes": 1,
            "modified_at_ns": 10,
        }
        for changes in ({"size_bytes": "1"}, {"unexpected": True}, {"type": "socket"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                FileEntry.model_validate({**valid, **changes})
        with self.assertRaises(ValidationError):
            TerminalJob.model_validate({"job_id": "incomplete"})

    def test_domain_and_application_do_not_import_panel_adapters(self) -> None:
        package = Path(control_panel_api.__file__).parent
        violations: list[str] = []
        forbidden = ("control_panel_api.infrastructure", "control_panel_api.presentation")
        for layer in ("domain", "application"):
            for source in (package / layer).rglob("*.py"):
                tree = ast.parse(source.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = (
                        [node.module or ""]
                        if isinstance(node, ast.ImportFrom)
                        else [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                    if any(name.startswith(forbidden) for name in names):
                        violations.append(str(source.relative_to(package)))
        self.assertEqual(violations, [], "inner layers must depend on ports, not adapters")
