from __future__ import annotations

from urllib.parse import urlsplit

from briareus_json_values import JsonObject
from fastapi import APIRouter, Request

from control_panel_api.dashboard_state import build_dashboard_state

from .context import WebApiContext


class OverviewRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/bootstrap", self.bootstrap, methods=["GET"])
        router.add_api_route("/dashboard", self.dashboard, methods=["GET"])

    def bootstrap(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        return {
            "product": "Briareus Control Panel API",
            "environment": "runtime",
            "node": {
                "id": self.context.identity.verifier.settings.node_id,
                "hostname": urlsplit(self.context.public_origin).hostname or "localhost",
                "origin": self.context.public_origin,
            },
            "navigation": [
                {"id": "overview", "label": "Overview", "enabled": True},
                {"id": "accounts", "label": "Accounts", "enabled": True},
                {"id": "calls", "label": "MCP Calls", "enabled": True},
                {"id": "files", "label": "Files", "enabled": True},
                {"id": "terminal", "label": "Terminal", "enabled": True},
                {"id": "browser", "label": "Browser", "enabled": True},
                {"id": "analysis", "label": "Analysis", "enabled": True},
                {"id": "settings", "label": "Settings", "enabled": True},
            ],
        }

    async def dashboard(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        api = self.context.available()
        return await build_dashboard_state(api.accounts, api.audit, api.snapshots)
