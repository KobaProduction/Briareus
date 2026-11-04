"""Cross-capability client contracts: validation, cache isolation and explicit ownership."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

from briareus_browser_policy_client import browser_launcher_policy, browser_runtime_policy
from briareus_cache.settings import ValkeySettings
from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_json_values import JsonObject, JsonValue, json_object, json_value
from briareus_mcp_policy_client import mcp_runtime_policy
from briareus_oauth_sessions import OAuthSessionEvent
from briareus_oauth_sessions_client import record_oauth_session
from pydantic import ValidationError


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, JsonValue] = {}

    def key(self, *parts: str) -> str:
        return ":".join(parts)

    def get_json(self, key: str) -> JsonValue | None:
        return self.values.get(key)

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        self.values[key] = json_value(value)
        return True

    def delete(self, *keys: str) -> bool:
        for key in keys:
            self.values.pop(key, None)
        return True


class WireClient(ControlPanelClient):
    def __init__(self) -> None:
        self.memory_cache = MemoryCache()
        super().__init__(
            ControlPanelClientSettings(service_token="contract-only-token"),
            cache=self.memory_cache,
            cache_settings=ValkeySettings(password="contract-only-password"),
        )
        self.replies: dict[str, JsonObject] = {}
        self.calls: list[tuple[str, str, JsonObject | None, bool]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: JsonObject | None = None,
        expect_body: bool = True,
        fresh_connection: bool = False,
    ) -> JsonObject:
        del query, fresh_connection
        self.calls.append((method, path, payload, expect_body))
        return self.replies.get(path, {})


class NarrowPolicyClientContracts(unittest.TestCase):
    def test_typed_policy_caches_are_isolated_and_reused(self) -> None:
        client = WireClient()
        client.replies = {
            "/internal/runtime-settings/browser": {"call_timeout_seconds": 310},
            "/internal/runtime-settings/mcp": {"call_timeout_seconds": 12},
        }
        self.assertEqual(browser_runtime_policy(client).call_timeout_seconds, 310)
        self.assertEqual(mcp_runtime_policy(client).call_timeout_seconds, 12)
        self.assertEqual(browser_runtime_policy(client).call_timeout_seconds, 310)
        self.assertEqual(mcp_runtime_policy(client).call_timeout_seconds, 12)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(client.memory_cache.values), 2)

    def test_invalid_policy_never_poisoned_the_cache_and_invalid_cached_data_fails_closed(
        self,
    ) -> None:
        client = WireClient()
        path = "/internal/runtime-settings/browser"
        client.replies[path] = {"external_enabled": True}
        with self.assertRaises(ValidationError):
            browser_runtime_policy(client)
        self.assertEqual(client.memory_cache.values, {})
        client.replies[path] = {"external_enabled": False}
        self.assertFalse(browser_runtime_policy(client).external_enabled)
        client.memory_cache.values[client.cache_keys.browser_policy()] = {
            "external_mcp_url": "https://user:private@example.test/mcp"
        }
        with self.assertRaises(ValidationError):
            browser_runtime_policy(client)
        self.assertEqual(len(client.calls), 2)

    def test_launcher_credentials_are_fresh_and_oauth_reporting_never_uses_policy_cache(
        self,
    ) -> None:
        client = WireClient()
        path = "/internal/runtime-settings/browser-launcher"
        client.replies[path] = {"extension_token": "first-contract-token"}
        self.assertEqual(browser_launcher_policy(client).extension_token, "first-contract-token")
        client.replies[path] = {"extension_token": "rotated-contract-token"}
        self.assertEqual(browser_launcher_policy(client).extension_token, "rotated-contract-token")
        event = OAuthSessionEvent(
            client_id="client",
            resource="https://mcp.example.test/server/mcp",
            event="access_used",
            access_jti="public-test-jti",
        )
        record_oauth_session(client, event)
        method, target, payload, expect_body = client.calls[-1]
        self.assertEqual(
            (method, target, expect_body), ("POST", "/internal/oauth-sessions/events", False)
        )
        self.assertEqual(json_object(payload)["resource"], event.resource)
        self.assertEqual(client.memory_cache.values, {})

    def test_core_transport_does_not_load_optional_policy_or_oauth_models(self) -> None:
        script = """
import sys
from briareus_control_panel_client.control_panel_client import ControlPanelClient
optional = ('briareus_browser_policy', 'briareus_mcp_policy', 'briareus_terminal_policy',
            'briareus_github_policy', 'briareus_gitlab_policy', 'briareus_oauth_sessions')
assert not any(name in sys.modules for name in optional), sorted(sys.modules)
assert not hasattr(ControlPanelClient, 'browser_runtime_policy')
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(sys.path)
        reply = subprocess.run(
            [sys.executable, "-c", script],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(reply.returncode, 0, reply.stderr)
