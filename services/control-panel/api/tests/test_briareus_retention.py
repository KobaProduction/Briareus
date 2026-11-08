from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_github_policy import GitHubRuntimePolicy
from briareus_gitlab_policy import GitLabRuntimePolicy
from briareus_mcp_policy import McpRuntimePolicy
from briareus_terminal_policy import TerminalRuntimePolicy
from control_panel_api.application.services import InvocationAuditService
from control_panel_api.presentation.admin_routes.contracts import SettingsPayload
from control_panel_api.presentation.admin_routes.settings import SettingsRoutes
from fastapi import Request
from pydantic import ValidationError


class RetentionContracts(unittest.TestCase):
    def test_cleanup_notifies_live_journal_only_after_actual_deletion(self) -> None:
        repository = Mock()
        repository.cleanup.side_effect = [8, 0]
        publisher = Mock()
        audit = InvocationAuditService(repository, publisher=publisher)
        self.assertEqual(audit.cleanup(), 8)
        publisher.assert_called_once_with("mcp.calls", "retention_applied", {"removed": 8})
        self.assertEqual(audit.cleanup(), 0)
        self.assertEqual(publisher.call_count, 1)

    def test_policy_save_applies_saved_retention_before_returning(self) -> None:
        context = Mock()
        context.settings_update_lock = asyncio.Lock()
        context.publish_management_event = AsyncMock()
        api = context.mutation.return_value
        api.runtime_settings.browser_policy.return_value = BrowserRuntimePolicy()
        api.runtime_settings.terminal_policy.return_value = TerminalRuntimePolicy(
            max_concurrent_processes=7,
        )
        for operation in (
            api.config.update,
            api.runtime_settings.update_terminal_policy,
            api.runtime_settings.update_mcp_policy,
            api.runtime_settings.update_browser_policy,
            api.runtime_settings.update_github_policy,
            api.runtime_settings.update_gitlab_policy,
        ):
            operation.side_effect = lambda policy, **_kwargs: policy
        routes = SettingsRoutes(context)
        with (
            patch.object(routes, "check_revision", AsyncMock(return_value=None)),
            patch.object(routes, "github_policy", AsyncMock(return_value=GitHubRuntimePolicy())),
            patch.object(routes, "gitlab_policy", AsyncMock(return_value=GitLabRuntimePolicy())),
            patch.object(routes, "reverse_settings", AsyncMock(return_value={})),
            patch.object(routes, "disconnect_changed_browser", AsyncMock()),
            patch.object(routes, "settings_revision", return_value="revision"),
        ):
            response = asyncio.run(
                routes.settings_update(
                    SettingsPayload(
                        logging_retention_days=7,
                        logging_max_records=100,
                        mcp_call_timeout_seconds=0,
                    ),
                    Request({"type": "http"}),
                )
            )
        self.assertEqual(
            api.runtime_settings.update_terminal_policy.call_args.args[0].max_concurrent_processes,
            7,
        )
        api.audit.cleanup.assert_called_once_with()
        self.assertEqual(response["mcp"], {"call_timeout_seconds": 0})
        self.assertEqual(api.config.update.call_args.args[0].logging_retention_days, 7)

    def test_global_call_timeout_defaults_to_unlimited_and_rejects_negative(self) -> None:
        self.assertEqual(McpRuntimePolicy().call_timeout_seconds, 0)
        self.assertEqual(SettingsPayload().mcp_call_timeout_seconds, 0)
        for model, field in (
            (McpRuntimePolicy, "call_timeout_seconds"),
            (SettingsPayload, "mcp_call_timeout_seconds"),
        ):
            with self.assertRaises(ValidationError):
                model.model_validate({field: -1})
