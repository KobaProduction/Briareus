from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_service_discovery import ServiceDiscovery
from briareus_terminal_policy import TerminalRuntimePolicy
from control_panel_api.application.identity import PanelTokenIdentity
from control_panel_api.application.services import (
    AccountService,
    InvocationAuditService,
    RuntimeSettingsService,
)
from control_panel_api.domain.admin_data.browser import BrowserStatus, BrowserTabPolicy
from control_panel_api.presentation.admin_routes.context import WebApiContext
from control_panel_api.presentation.admin_routes.contracts import SettingsPayload
from control_panel_api.presentation.admin_routes.overview import OverviewRoutes
from control_panel_api.presentation.admin_routes.settings import SettingsRoutes
from control_panel_api.presentation.api import ApiServices, build_internal_router
from control_panel_api.presentation.web_api import WebApiServices, build_admin_api_router
from control_panel_api.settings import ControlPanelSettings
from fastapi import FastAPI, Request
from starlette.testclient import TestClient


class ApiRouteContracts(unittest.TestCase):
    def test_browser_tab_policy_uses_authenticated_mutation_and_validates_limits(self) -> None:
        services = Mock(spec=WebApiServices)
        services.web = Mock(set_tab_policy=AsyncMock(return_value=BrowserStatus(
            running=True,
            tab_policy=BrowserTabPolicy(
                max_tabs=20, idle_close_enabled=True, idle_timeout_seconds=300
            ),
        )))
        services.realtime = None
        app = FastAPI()
        app.include_router(build_admin_api_router(
            ControlPanelSettings(), services, identity=Mock(spec=PanelTokenIdentity),
            public_origin="https://panel.example.test",
        ))
        payload = {"max_tabs": 20, "idle_close_enabled": True, "idle_timeout_seconds": 300}
        with (
            patch.object(WebApiContext, "mutation", return_value=services) as mutation,
            TestClient(app) as client,
        ):
            response = client.put("/admin/api/browser/tabs/policy", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["tab_policy"], payload)
            mutation.assert_called_once()
            for invalid in ({"max_tabs": 0}, {"max_tabs": 101},
                            {"idle_timeout_seconds": 0}, {"idle_close_enabled": "false"}):
                result = client.put(
                    "/admin/api/browser/tabs/policy", json={**payload, **invalid}
                )
                self.assertEqual(result.status_code, 422)
            mutation.assert_called_once()
        services.web.set_tab_policy.assert_awaited_once_with(**payload)

    def test_disconnected_provider_is_not_invoked_and_reconnect_requires_no_api_restart(
        self,
    ) -> None:
        discovery = Mock(spec=ServiceDiscovery)
        discovery.connected = AsyncMock(return_value=False)
        services = Mock(spec=WebApiServices)
        services.web = Mock(status=AsyncMock(return_value=BrowserStatus(running=True)))
        app = FastAPI()
        app.include_router(
            build_admin_api_router(
                ControlPanelSettings(),
                services,
                identity=Mock(spec=PanelTokenIdentity),
                public_origin="https://panel.example.test",
                discovery=discovery,
            )
        )
        with (
            patch.object(WebApiContext, "require_user", return_value="user-1"),
            TestClient(app) as client,
        ):
            response = client.get("/admin/api/browser/state")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["detail"]["code"], "service_unavailable")
            services.web.status.assert_not_called()
            discovery.connected.return_value = True
            self.assertEqual(client.get("/admin/api/browser/state").status_code, 200)
            services.web.status.assert_awaited_once()

    def test_bootstrap_uses_the_configured_node_even_when_the_domain_is_an_alias(self) -> None:
        for city in ("tambov", "moscow"):
            origin = "https://gateway.example.test"
            identity = Mock(spec=PanelTokenIdentity)
            identity.verifier = Mock(settings=Mock(node_id=city))
            context = WebApiContext(
                ControlPanelSettings(),
                None,
                identity,
                origin,
            )
            with patch.object(context, "require_user", return_value="user-1"):
                response = asyncio.run(OverviewRoutes(context).bootstrap(Request({"type": "http"})))
            self.assertEqual(
                response.node.to_json(),
                {
                    "id": city,
                    "hostname": "gateway.example.test",
                    "origin": origin,
                },
            )

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
