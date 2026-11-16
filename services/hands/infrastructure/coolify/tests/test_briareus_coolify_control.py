from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from briareus_account_contracts import ResolvedAccount
from briareus_coolify.client import CoolifyClient, CoolifyClientError
from briareus_coolify.variable_access import (
    VariableReadConfirmation,
    available_value,
    masked_preview,
    safe_shared_variable,
)
from briareus_hand_runtime.tool_observability import (
    invocation_arguments_payload,
    invocation_result_payload,
)
from briareus_http_transport.http_transport import HttpTransportResponse
from briareus_json_values import JsonObject


def client() -> CoolifyClient:
    return CoolifyClient(
        ResolvedAccount(
            id="coolify-source",
            alias="test",
            provider="coolify",
            auth_type="coolify_api_token",
            base_url="https://coolify.example.test",
            credential="provider-bearer-secret",
            created_at="created",
            updated_at="revision-1",
        )
    )


def response(raw: object, status: int = 200) -> HttpTransportResponse:
    return HttpTransportResponse(
        status=status,
        headers={},
        body=json.dumps(raw).encode(),
        will_close=False,
    )


class CoolifyPermissionDiagnosticsTests(unittest.TestCase):
    def test_403_reports_required_permission_for_each_action(self) -> None:
        provider = client()
        actions = (
            ("read", lambda: provider.application("app-1")),
            ("read:sensitive", lambda: provider.application_logs("app-1")),
            ("read:sensitive", lambda: provider.service_logs("svc-1", "web")),
            ("read:sensitive", lambda: provider.deployment_logs("deployment-1")),
            ("read:sensitive", lambda: provider.shared_variables("team")),
            ("read:sensitive", lambda: provider.prepare_application_variable_read(
                "app-1", "API_TOKEN"
            )),
            ("deploy", lambda: provider.restart_application("app-1", confirm=True)),
            ("deploy", lambda: provider.restart_service("svc-1", confirm=True)),
            ("deploy", lambda: provider.deploy_application("app-1", confirm=True)),
            ("deploy", lambda: provider.deploy_service("svc-1", confirm=True)),
        )
        for permission, operation in actions:
            with self.subTest(required_permission=permission):
                upstream = response(
                    {"error": "raw-provider-private-value"}, status=403
                )
                with (
                    patch.object(provider._transport, "request", return_value=upstream),
                    self.assertRaises(CoolifyClientError) as raised,
                ):
                    operation()
                message = str(raised.exception)
                self.assertIn("HTTP 403 Forbidden", message)
                self.assertIn(f"'{permission}'", message)
                self.assertIn("Permissions and Access", message)
                self.assertIn("resource", message)
                self.assertNotIn("raw-provider-private-value", message)
                self.assertNotIn("provider-bearer-secret", message)

    def test_401_identifies_invalid_token_not_missing_read_sensitive(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request", return_value=response({}, 401)),
            self.assertRaises(CoolifyClientError) as raised,
        ):
            provider.application_logs("app-1")
        self.assertIn("HTTP 401 Unauthorized", str(raised.exception))
        self.assertIn("invalid", str(raised.exception))
        self.assertNotIn("provider-bearer-secret", str(raised.exception))

    def test_404_does_not_invent_missing_permissions(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request", return_value=response({}, 404)),
            self.assertRaises(CoolifyClientError) as raised,
        ):
            provider.application("unknown")
        self.assertEqual(str(raised.exception), "Coolify HTTP 404")

    def test_account_summary_describes_requirements_without_claiming_grants(self) -> None:
        provider = client()
        result = provider.account_summary()
        matrix = result["required_permissions"]
        self.assertIsInstance(matrix, dict)
        self.assertEqual(matrix["runtime_and_deployment_logs"], "read:sensitive")
        self.assertEqual(matrix["restart_and_deploy"], "deploy")
        self.assertFalse(result["effective_token_permissions_verified"])
        self.assertNotIn("provider-bearer-secret", json.dumps(result))

    def test_redacted_app_value_reports_required_permission(self) -> None:
        from briareus_coolify.variable_access import app_variable_value

        with self.assertRaises(ValueError) as raised:
            app_variable_value({"key": "API_TOKEN", "value": "************"})
        self.assertIn("read:sensitive", str(raised.exception))
        self.assertIn("Admin/Owner", str(raised.exception))


class CoolifyApplicationControlTests(unittest.TestCase):
    def test_runtime_logs_are_redacted_and_bound_to_one_compose_service(self) -> None:
        provider = client()
        raw = {"logs": "DB_PASSWORD=superprivate\nAuthorization: Bearer bearer-value\nready"}
        with patch.object(provider._transport, "request", return_value=response(raw)) as request:
            result = provider.application_logs(
                "app-123", service_name="coolify-mcp-hand", lines=25, max_chars=1000
            )
        logs = str(result["logs"])
        self.assertIn("ready", logs)
        self.assertNotIn("superprivate", logs)
        self.assertNotIn("bearer-value", logs)
        self.assertTrue(result["logs_available"])
        self.assertIn("applications/app-123/logs", request.call_args.args[1])
        self.assertIn("service_name=coolify-mcp-hand", request.call_args.args[1])
        self.assertIn("lines=25", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["reconnect_retries"], 1)

    def test_logs_403_does_not_fabricate_empty_journal(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request", return_value=response({}, 403)),
            self.assertRaisesRegex(CoolifyClientError, "Coolify HTTP 403"),
        ):
            provider.application_logs("app-id")

    def test_service_discovery_projects_only_safe_names_and_component_status(self) -> None:
        provider = client()
        raw = {
            "uuid": "svc1", "name": "worker", "status": "running",
            "docker_compose": "SHOULD-NEVER-LEAK",
            "applications": [
                {"uuid": "component1", "name": "web", "status": "running",
                 "environment": {"SECRET": "DONT-LEAK"}}
            ],
            "databases": [{"name": "db", "password": "DONT-LEAK"}],
        }
        with patch.object(provider._transport, "request", return_value=response([raw])):
            listed = provider.services()
        self.assertNotIn("SHOULD-NEVER-LEAK", json.dumps(listed))
        with patch.object(provider._transport, "request", return_value=response(raw)) as request:
            detail = provider.service("svc1")
        self.assertEqual(request.call_args.args[1], "/api/v1/services/svc1")
        self.assertEqual(detail["applications"][0]["name"], "web")
        self.assertNotIn("DONT-LEAK", json.dumps(detail))

    def test_service_logs_require_component_name_and_redact_content(self) -> None:
        provider = client()
        raw = {"logs": "API_TOKEN=secret-dont-leak\nservice running"}
        with patch.object(provider._transport, "request", return_value=response(raw)) as request:
            result = provider.service_logs("service", "web", lines=20)
        self.assertIn("service running", str(result["logs"]))
        self.assertNotIn("secret-dont-leak", json.dumps(result))
        self.assertIn(
            "/api/v1/services/service/logs?sub_service_name=web&lines=20",
            request.call_args.args[1],
        )
        with (
            patch.object(provider._transport, "request") as request,
            self.assertRaises(ValueError),
        ):
            provider.service_logs("service", "")
        request.assert_not_called()

    def test_service_deploy_requires_explicit_confirmation(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request") as request,
            self.assertRaises(ValueError),
        ):
            provider.deploy_service("service")
        request.assert_not_called()
        with patch.object(
            provider._transport, "request",
            return_value=response({"deployments": [
                {"resource_uuid": "service", "deployment_uuid": "dep1", "secrets": "NO"}
            ]}),
        ) as request:
            result = provider.deploy_service("service", confirm=True)
        self.assertEqual(result["operation"], "deploy_service")
        self.assertNotIn("NO", json.dumps(result))
        self.assertIn("/api/v1/deploy?uuid=service&force=false", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["reconnect_retries"], 0)

    def test_log_request_window_is_checked_before_upstream(self) -> None:
        provider = client()
        with patch.object(provider._transport, "request") as request:
            for lines, max_chars in ((0, 100), (5001, 100), (100, 0)):
                with self.subTest(lines=lines, max_chars=max_chars), self.assertRaises(ValueError):
                    provider.application_logs("app", lines=lines, max_chars=max_chars)
        request.assert_not_called()

    def test_restart_requires_confirmation_and_does_not_retry_post(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request") as request,
            self.assertRaises(ValueError),
        ):
            provider.restart_application("app-id")
        request.assert_not_called()
        with patch.object(
            provider._transport,
            "request",
            return_value=response({"message": "Restart queued", "deployment_uuid": "dep-1"}),
        ) as request:
            result = provider.restart_application("app-id", confirm=True)
        self.assertEqual(result["operation"], "restart")
        self.assertEqual(result["deployment_uuid"], "dep-1")
        self.assertEqual(request.call_args.args, ("POST", "/api/v1/applications/app-id/restart"))
        self.assertEqual(request.call_args.kwargs["reconnect_retries"], 0)

    def test_service_restart_is_single_resource_and_confirmed(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request") as request,
            self.assertRaises(ValueError),
        ):
            provider.restart_service("service-id")
        request.assert_not_called()
        with patch.object(
            provider._transport, "request",
            return_value=response({"message": "Service restarting"}),
        ) as request:
            result = provider.restart_service("service-id", confirm=True, pull_latest=False)
        self.assertEqual(result["operation"], "restart_service")
        self.assertEqual(
            request.call_args.args,
            ("POST", "/api/v1/services/service-id/restart?latest=false"),
        )
        self.assertEqual(request.call_args.kwargs["reconnect_retries"], 0)

    def test_deploy_only_one_uuid_without_force_by_default(self) -> None:
        provider = client()
        with patch.object(provider._transport, "request") as request:
            with self.assertRaises(ValueError):
                provider.deploy_application("app-id")
            with self.assertRaises(ValueError):
                provider.deploy_application("app-id,bad-app", confirm=True)
        request.assert_not_called()
        with patch.object(
            provider._transport,
            "request",
            return_value=response({
                "deployments": [
                    {
                        "resource_uuid": "app-id",
                        "deployment_uuid": "d123",
                        "message": "Queued",
                        "configuration_snapshot": "NEVER-DISCLOSE",
                    }
                ]
            }),
        ) as request:
            result = provider.deploy_application("app-id", confirm=True)
        self.assertEqual(result["force_rebuild"], False)
        self.assertNotIn("NEVER-DISCLOSE", json.dumps(result))
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertIn("/api/v1/deploy?uuid=app-id&force=false", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["reconnect_retries"], 0)


class CoolifySharedVariableTests(unittest.TestCase):
    def test_shared_variable_status_and_masks_never_return_plaintext(self) -> None:
        provider = client()
        raw: list[JsonObject] = [
            {"key": "SHARED_SECRET", "real_value": "ab-hidden-value-xy"},
            {"key": "SHORT", "value": "abcd"},
            {"key": "EMPTY", "value": ""},
            {"key": "LOCKED", "is_shown_once": True, "real_value": "hidden-locked"},
            {"key": "REDACTED", "value": "************"},
        ]
        with patch.object(provider._transport, "request", return_value=response(raw)) as request:
            status = provider.shared_variables("project", project_uuid="project-123")
        self.assertEqual(request.call_args.args[1], "/api/v1/projects/project-123/envs")
        self.assertNotIn("real_value", json.dumps(status))
        self.assertNotIn("hidden-value", json.dumps(status))
        variables = {item["key"]: item for item in status["variables"]}
        self.assertEqual(variables["SHARED_SECRET"]["value_length"], len("ab-hidden-value-xy"))
        self.assertTrue(variables["SHARED_SECRET"]["configured"])
        self.assertFalse(variables["EMPTY"]["configured"])
        self.assertIsNone(variables["LOCKED"]["value_length"])
        self.assertIsNone(variables["REDACTED"]["configured"])
        with patch.object(provider._transport, "request", return_value=response(raw)):
            masked = provider.shared_variables("project", project_uuid="project-123", masked=True)
        text = json.dumps(masked)
        self.assertNotIn("hidden-value", text)
        rows = {item["key"]: item for item in masked["variables"]}
        self.assertEqual(rows["SHARED_SECRET"]["masked_value"], "ab" + "*" * 14 + "xy")
        self.assertEqual(rows["SHORT"]["masked_value"], "****")
        self.assertIsNone(rows["LOCKED"]["masked_value"])

    def test_shared_scope_restrictions_are_checked_before_network(self) -> None:
        provider = client()
        with patch.object(provider._transport, "request") as request:
            for scope, kwargs in (
                ("team", {"project_uuid": "x"}),
                ("project", {}),
                ("environment", {"project_uuid": "x"}),
                ("server", {"server_uuid": "", "project_uuid": "x"}),
                ("invalid", {}),
            ):
                with self.subTest(scope=scope), self.assertRaises(ValueError):
                    provider.shared_variables(scope, **kwargs)
        request.assert_not_called()

    def test_explicit_team_environment_and_server_routes(self) -> None:
        provider = client()
        with patch.object(provider._transport, "request", return_value=response([])) as request:
            provider.shared_variables("team")
            provider.shared_variables("environment", project_uuid="p", environment_uuid="e")
            provider.shared_variables("server", server_uuid="s")
        paths = [call.args[1] for call in request.call_args_list]
        self.assertEqual(paths, [
            "/api/v1/team/envs",
            "/api/v1/projects/p/environments/e/envs",
            "/api/v1/servers/s/envs",
        ])

    def test_locked_and_redacted_upstream_values_are_not_exposed(self) -> None:
        locked: JsonObject = {"is_shown_once": True, "real_value": "full-locked-secret"}
        self.assertIsNone(available_value(locked))
        self.assertIsNone(safe_shared_variable(locked, masked=True)["masked_value"])
        self.assertIsNone(available_value({"value": "********"}))
        self.assertEqual(masked_preview("abcd"), "****")


class CoolifyApplicationVariableConfirmationTests(unittest.TestCase):
    def test_application_metadata_never_returns_value(self) -> None:
        provider = client()
        raw = [{"key": "API_TOKEN", "value": "private-app-value", "is_shared": False}]
        with patch.object(provider._transport, "request", return_value=response(raw)):
            result = provider.application_variables("app")
        self.assertNotIn("private-app-value", json.dumps(result))
        variable = result["variables"][0]
        self.assertTrue(variable["configured"])
        self.assertEqual(variable["value_length"], len("private-app-value"))
        self.assertFalse(result["values_exposed"])

    def test_value_read_requires_two_scoped_calls_and_is_single_use(self) -> None:
        provider = client()
        raw = [{"key": "API_TOKEN", "value": "private-app-value", "is_shared": False}]
        with patch.object(provider._transport, "request", return_value=response(raw)) as request:
            staged = provider.prepare_application_variable_read("app", "API_TOKEN")
            token = staged["confirmation_token"]
            self.assertFalse(staged["value_exposed"])
            self.assertNotIn("private-app-value", json.dumps(staged))
            assert isinstance(token, str)
            with self.assertRaisesRegex(ValueError, "Explicit permission"):
                provider.confirm_application_variable_read(
                    "app", "API_TOKEN", confirmation_token=token, permission_confirmed=False,
                    purpose="Operator authorized this specific application's key"
                )
            with self.assertRaisesRegex(ValueError, "specific"):
                provider.confirm_application_variable_read(
                    "app", "API_TOKEN", confirmation_token=token, permission_confirmed=True,
                    purpose="short"
                )
            with self.assertRaisesRegex(ValueError, "not valid"):
                provider.confirm_application_variable_read(
                    "other-app", "API_TOKEN", confirmation_token=token,
                    permission_confirmed=True,
                    purpose="Operator authorized this specific application's key"
                )
            with self.assertRaisesRegex(ValueError, "already used"):
                provider.confirm_application_variable_read(
                    "app", "API_TOKEN", confirmation_token=token, permission_confirmed=True,
                    purpose="Operator authorized this specific application's key"
                )
            token = provider.prepare_application_variable_read("app", "API_TOKEN")[
                "confirmation_token"
            ]
            assert isinstance(token, str)
            result = provider.confirm_application_variable_read(
                "app", "API_TOKEN", confirmation_token=token, permission_confirmed=True,
                purpose="Operator authorized this specific application's key"
            )
        self.assertEqual(result["value"], "private-app-value")
        self.assertTrue(result["read_confirmed"])
        self.assertEqual(request.call_count, 3)

    def test_shared_locked_or_reference_key_is_never_readable(self) -> None:
        provider = client()
        raw_rows = [
            {"key": "X", "value": "hidden", "is_shared": True},
            {"key": "X", "value": "{{environment.X}}", "real_value": "hidden", "is_shared": False},
            {"key": "X", "value": "locked", "is_shown_once": True},
            {"key": "X", "value": "********"},
        ]
        with patch.object(provider._transport, "request") as request:
            for raw in raw_rows:
                request.return_value = response([raw])
                with self.subTest(raw=raw["key"]), self.assertRaises(ValueError):
                    provider.prepare_application_variable_read("app", "X")

    def test_one_time_challenge_expires_without_storing_values(self) -> None:
        approvals = VariableReadConfirmation()
        with patch("briareus_coolify.variable_access.time.monotonic", return_value=10.0):
            token = approvals.issue("account", "app", "KEY")
        with (
            patch("briareus_coolify.variable_access.time.monotonic", return_value=131.0),
            self.assertRaisesRegex(ValueError, "expired"),
        ):
            approvals.consume(
                token, account="account", application="app", variable="KEY",
                permission_confirmed=True, purpose="Operator explicitly approved this read"
            )
        self.assertNotIn("private-app-value", repr(approvals))

    def test_sensitive_values_never_enter_invocation_audit(self) -> None:
        request = {
            "account_id": "id", "application_uuid": "app", "key": "API_KEY",
            "confirmation_token": "one-use-challenge-secret",
            "purpose": "Authorized request, do not audit purpose",
        }
        arguments = invocation_arguments_payload(
            "coolify", request, "coolify_confirm_application_variable_read"
        )
        self.assertNotIn("one-use-challenge-secret", arguments)
        self.assertNotIn("do not audit", arguments)
        result = invocation_result_payload(
            "coolify", {"value": "SECRET-VALUE"}, "coolify_confirm_application_variable_read"
        )
        self.assertNotIn("SECRET-VALUE", result)
        for tool in ("coolify_shared_variables", "coolify_get_application_logs"):
            result = invocation_result_payload("coolify", {"logs": "SECRET-VALUE"}, tool)
            self.assertNotIn("SECRET-VALUE", result)


if __name__ == "__main__":
    unittest.main()
