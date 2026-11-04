from __future__ import annotations

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_json_values import json_object
from briareus_oauth_sessions import OAuthSessionEvent


def record_oauth_session(client: ControlPanelClient, event: OAuthSessionEvent) -> None:
    client.request(
        "POST",
        "/internal/oauth-sessions/events",
        payload=json_object(event.model_dump(mode="json"), context="oauth session event"),
        expect_body=False,
    )
