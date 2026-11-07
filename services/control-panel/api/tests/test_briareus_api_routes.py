from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_terminal_policy import TerminalRuntimePolicy
from control_panel_api.application.identity import PanelTokenIdentity
from control_panel_api.application.services import (
    AccountService,
    InvocationAuditService,
    RuntimeSettingsService,
)
from control_panel_api.presentation.admin_routes.context import WebApiContext
from control_panel_api.presentation.admin_routes.contracts import SettingsPayload
from control_panel_api.presentation.admin_routes.overview import OverviewRoutes
from control_panel_api.presentation.admin_routes.settings import SettingsRoutes
from control_panel_api.presentation.api import ApiServices, build_internal_router
from control_panel_api.presentation.web_api import build_admin_api_router
from control_panel_api.settings import ControlPanelSettings
from fastapi import FastAPI, Request
from starlette.testclient import TestClient


class ApiRouteContracts(unittest.TestCase):
    def test_bootstrap_identifies_the_node_from_its_canonical_origin(self) -> None:
        for city in ("tambov", "moscow"):
            origin = f"https://{city}.briareus.example.test"
            context = WebApiContext(
                ControlPanelSettings(), None, Mock(spec=PanelTokenIdentity), origin,
            )
            with patch.object(context, "require_user", return_value="user-1"):
                response = OverviewRoutes(context).bootstrap(Request({"type": "http"}))
            self.assertEqual(response["node"], {
                "id": city, "hostname": f"{city}.briareus.example.test", "origin": origin,
            })

    def test_internal_authorization_rejects_missing_and_incorrect_credentials(self) -> None:
        runtime = Mock(spec=RuntimeSettingsService)
        runtime.terminal_policy.return_value = TerminalRuntimePolicy()
        services = ApiServices(
            Mock(spec=AccountService),
            Mock(spec=InvocationAuditService),
            runtime,
            "internal-test-token",
        )
        app = FastAPI()
        app.include_router(build_internal_router(services))
        with TestClient(app) as client:
            for headers in ({}, {"Authorization": "Bearer incorrect"}):
                response = client.get("/internal/runtime-settings/terminal", headers=headers)
                self.assertEqual(response.status_code, 401)
            runtime.terminal_policy.assert_not_called()
            response = client.get(
                "/internal/runtime-settings/terminal",
                headers={"Authorization": "Bearer internal-test-token"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), TerminalRuntimePolicy().to_json())
        runtime.terminal_policy.assert_called_once_with()

    def test_admin_read_requires_identity_before_services_are_available(self) -> None:
        app = FastAPI()
        identity = Mock(spec=PanelTokenIdentity)
        app.include_router(
            build_admin_api_router(
                ControlPanelSettings(),
                identity=identity,
                public_origin="https://panel.example.test",
            )
        )
        with TestClient(app) as client:
            for path in ("/bootstrap", "/accounts", "/calls", "/settings", "/browser/state"):
                self.assertEqual(client.get("/admin/api" + path).status_code, 401)

    def test_partial_browser_settings_preserve_omissions_and_accept_false(
        self,
    ) -> None:
        context = WebApiContext(
            ControlPanelSettings(),
            None,
            Mock(spec=PanelTokenIdentity),
            "https://panel.example.test",
        )
        routes = SettingsRoutes(context)
        current = BrowserRuntimePolicy(
            external_enabled=True,
            external_mcp_url="http://browser.example.test/mcp",
            auto_disconnect_enabled=True,
            idle_timeout_seconds=720,
            profile_dir_name="Profile A",
            extension_token_configured=True,
        )
        self.assertEqual(routes.browser_policy(SettingsPayload(), current), current)
        updated = routes.browser_policy(SettingsPayload(browser_external_enabled=False), current)
        self.assertFalse(updated.external_enabled)
        self.assertTrue(updated.auto_disconnect_enabled)
        self.assertTrue(updated.extension_token_configured)
        self.assertEqual(updated.external_mcp_url, current.external_mcp_url)
        self.assertEqual(updated.profile_dir_name, current.profile_dir_name)
