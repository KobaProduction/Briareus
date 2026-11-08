from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from briareus_json_values import JsonObject, json_array
from briareus_service_catalog import BUILTIN_SERVICES
from fastapi import APIRouter, Request

from control_panel_api.dashboard_state import build_dashboard_state

from .context import WebApiContext


class OverviewRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/bootstrap", self.bootstrap, methods=["GET"])
        router.add_api_route("/dashboard", self.dashboard, methods=["GET"])

    async def bootstrap(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        if self.context.discovery is not None:
            snapshot = await self.context.discovery.snapshot()
            services = [service.model_dump(mode="json") for service in snapshot.services]
            checked_at = snapshot.checked_at.isoformat()
        else:
            services = [
                {
                    "id": service.id,
                    "name": service.name,
                    "group": service.group,
                    "connected": False,
                    "mcp_path": service.mcp_path,
                }
                for service in BUILTIN_SERVICES
            ]
            checked_at = datetime.now(UTC).isoformat()
        return {
            "product": "Briareus Control Panel API",
            "environment": "runtime",
            "node": {
                "id": self.context.identity.verifier.settings.node_id,
                "hostname": urlsplit(self.context.public_origin).hostname or "localhost",
                "origin": self.context.public_origin,
            },
            "services": json_array(services, context="node MCP services"),
            "checked_at": checked_at,
        }

    async def dashboard(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        api = self.context.available()
        return await build_dashboard_state(api.accounts, api.audit, api.snapshots)
