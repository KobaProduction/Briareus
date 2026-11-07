from __future__ import annotations

import io
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import httpx
from node_registration import (
    ErrorCode,
    NodeRegistrationError,
    NodeSpec,
    RegistryConfig,
    ZitadelRoleRegistry,
    ensure_node,
    main,
)
from pydantic import SecretStr, ValidationError

TOKEN = "provisioner-test-credential-never-printed"
ORIGIN = "https://moscow.briareus.example.test"
BASE_ARGS = [
    "--origin",
    ORIGIN,
    "--issuer",
    "https://identity.example.test",
    "--project",
    "project",
    "--provider",
    "zitadel",
]


class RoleAuthority:
    def __init__(self, *, existing: bool = False, race: bool = False) -> None:
        self.exists = existing
        self.requests: list[httpx.Request] = []
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2) if race else None
        self.creates = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
        if request.url.path.endswith("/ListProjectRoles"):
            exists = self.exists
            if self.barrier:
                self.barrier.wait(timeout=5)
            roles = [{"projectId": "project", "key": "moscow", "group": "pre-existing"}]
            return httpx.Response(200, json={"projectRoles": roles if exists else []})
        if request.url.path.endswith("/AddProjectRole"):
            with self.lock:
                if self.exists:
                    return httpx.Response(409, json={"code": "already_exists"})
                self.exists = True
                self.creates += 1
            return httpx.Response(200, json={"creationDate": "2026-11-08T00:00:00Z"})
        raise AssertionError("Unexpected mutation or API outside role provisioning")


class NodeRegistrationContracts(unittest.TestCase):
    def config(self) -> RegistryConfig:
        return RegistryConfig(
            issuer="https://identity.example.test", project_id="project", token=SecretStr(TOKEN)
        )

    def test_new_node_creates_its_role_and_repeat_onboarding_reuses_it(self) -> None:
        authority = RoleAuthority()
        with httpx.Client(transport=httpx.MockTransport(authority.handle)) as client:
            registry = ZitadelRoleRegistry(self.config(), client)
            first = ensure_node(NodeSpec(origin=ORIGIN), registry)
            second = ensure_node(NodeSpec(origin=ORIGIN), registry)
        self.assertEqual((first.status, second.status), ("created", "existing"))
        self.assertEqual(first.runtime.required_role, "moscow")
        self.assertEqual(authority.creates, 1)
        create = next(r for r in authority.requests if r.url.path.endswith("AddProjectRole"))
        self.assertEqual(
            json.loads(create.content),
            {
                "projectId": "project",
                "roleKey": "moscow",
                "displayName": "Moscow",
                "group": "Nodes",
            },
        )
        self.assertTrue(all(r.method == "POST" for r in authority.requests))

    def test_existing_role_is_reused_without_renaming_or_touching_user_assignments(self) -> None:
        authority = RoleAuthority(existing=True)
        with httpx.Client(transport=httpx.MockTransport(authority.handle)) as client:
            result = ensure_node(
                NodeSpec(origin=ORIGIN), ZitadelRoleRegistry(self.config(), client)
            )
        self.assertEqual(result.status, "existing")
        self.assertEqual(len(authority.requests), 1)
        self.assertTrue(authority.requests[0].url.path.endswith("ListProjectRoles"))
        query = json.loads(authority.requests[0].content)
        self.assertEqual(query["filters"][0]["roleKeyFilter"]["key"], "moscow")

    def test_two_simultaneous_installers_succeed_with_one_creation(self) -> None:
        authority = RoleAuthority(race=True)

        def onboard(_index: int) -> str:
            with httpx.Client(transport=httpx.MockTransport(authority.handle)) as client:
                return ensure_node(
                    NodeSpec(origin=ORIGIN), ZitadelRoleRegistry(self.config(), client)
                ).status

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(onboard, range(2)))
        self.assertCountEqual(statuses, ["created", "existing"])
        self.assertEqual(authority.creates, 1)

    def test_invalid_origins_and_missing_credentials_fail_before_provisioning(self) -> None:
        for value in (
            "http://moscow.example",
            "https://u:p@moscow.example",
            "https://moscow.example/path",
            "https://moscow.example?token=private",
            "https://127.0.0.1",
            "https://bad_label.example",
        ):
            with self.subTest(origin=value), self.assertRaises(ValidationError):
                NodeSpec(origin=value)
        with self.assertRaises(ValidationError):
            self.config().model_validate(
                {
                    "issuer": "https://identity.example.test",
                    "project_id": "project",
                    "token": SecretStr(""),
                }
            )

    def test_credentials_do_not_follow_redirects_and_provider_bodies_never_escape(self) -> None:
        for status in (302, 401, 403, 429, 500):
            calls: list[httpx.Request] = []

            def response(
                request: httpx.Request,
                request_log: list[httpx.Request] = calls,
                code: int = status,
            ) -> httpx.Response:
                request_log.append(request)
                return httpx.Response(
                    code, headers={"Location": "https://elsewhere.example"}, text=TOKEN
                )

            with (
                httpx.Client(transport=httpx.MockTransport(response)) as client,
                self.subTest(status=status),
                self.assertRaises(NodeRegistrationError) as caught,
            ):
                ensure_node(NodeSpec(origin=ORIGIN), ZitadelRoleRegistry(self.config(), client))
            self.assertEqual(len(calls), 1)
            self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn(TOKEN, repr(self.config()))

    def test_oversized_and_malformed_provider_responses_fail_closed(self) -> None:
        for body in (b"[]", b"not json", b"x" * 65537):
            with (
                httpx.Client(
                    transport=httpx.MockTransport(
                        lambda _r, content=body: httpx.Response(200, content=content)
                    )
                ) as client,
                self.assertRaises(NodeRegistrationError),
            ):
                ensure_node(NodeSpec(origin=ORIGIN), ZitadelRoleRegistry(self.config(), client))

    def test_creation_timeout_does_not_retry_or_start_deployment(self) -> None:
        calls: list[str] = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("ListProjectRoles"):
                return httpx.Response(200, json={})
            raise httpx.ReadTimeout(TOKEN)

        with (
            httpx.Client(transport=httpx.MockTransport(handle)) as client,
            self.assertRaises(NodeRegistrationError) as caught,
        ):
            ensure_node(NodeSpec(origin=ORIGIN), ZitadelRoleRegistry(self.config(), client))
        self.assertEqual(caught.exception.code, ErrorCode.UNCERTAIN)
        self.assertEqual(len(calls), 2)


class NodeOnboardingCliContracts(unittest.TestCase):
    def test_one_command_ensures_role_then_supplies_node_settings_to_deployment(self) -> None:
        authority = RoleAuthority(existing=True)
        with (
            patch(
                "node_registration._cli.httpx.Client",
                return_value=httpx.Client(transport=httpx.MockTransport(authority.handle)),
            ),
            patch("node_registration._deployment.subprocess.run") as run,
            patch.dict(os.environ, {"ZITADEL_PROVISIONING_TOKEN": TOKEN}),
            redirect_stdout(io.StringIO()) as output,
        ):
            run.return_value.returncode = 0
            self.assertEqual(main([*BASE_ARGS, "--", "installer", "deploy"]), 0)
        self.assertEqual(run.call_args.args[0], ["installer", "deploy"])
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["OIDC_REQUIRED_ROLE"], "moscow")
        self.assertEqual(environment["CONTROL_PANEL_PUBLIC_BASE_URL"], ORIGIN)
        self.assertNotIn("ZITADEL_PROVISIONING_TOKEN", environment)
        self.assertNotIn(TOKEN, output.getvalue())

    def test_cli_errors_are_localized_and_do_not_echo_tokens_or_launch_deployment(self) -> None:
        for language in ("ru", "en"):
            with (
                patch.dict(os.environ, {"ZITADEL_PROVISIONING_TOKEN": ""}),
                patch("node_registration._deployment.subprocess.run") as run,
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(main([*BASE_ARGS, "--locale", language, "--", "installer"]), 1)
            run.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["code"], "invalid_registration_configuration")
            self.assertEqual(
                any(0x400 <= ord(char) <= 0x4FF for char in payload["message"]), language == "ru"
            )

    def test_failed_deploy_preserves_role_and_can_be_repeated(self) -> None:
        authority = RoleAuthority()
        for returncode in (1, 0):
            with (
                patch(
                    "node_registration._cli.httpx.Client",
                    return_value=httpx.Client(transport=httpx.MockTransport(authority.handle)),
                ),
                patch(
                    "node_registration._deployment.subprocess.run",
                    return_value=Mock(returncode=returncode),
                ),
                patch.dict(os.environ, {"ZITADEL_PROVISIONING_TOKEN": TOKEN}),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main([*BASE_ARGS, "--", "installer"]), returncode)
        self.assertEqual(authority.creates, 1)
