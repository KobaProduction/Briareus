from __future__ import annotations

import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
from briareus_oidc import OidcTokenSettings
from control_panel_api.infrastructure.node_registration import (
    ErrorCode,
    NodeProvisioningSettings,
    NodeRegistrationError,
    NodeSpec,
    RegistryConfig,
    ZitadelRoleRegistry,
    ensure_node_role,
)
from pydantic import SecretStr, ValidationError

TOKEN = "provisioner-test-credential-never-printed"


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
            first = registry.ensure(NodeSpec(node_id="moscow"))
            second = registry.ensure(NodeSpec(node_id="moscow"))
        self.assertEqual((first, second), (True, False))
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
            result = ZitadelRoleRegistry(self.config(), client).ensure(NodeSpec(node_id="moscow"))
        self.assertFalse(result)
        self.assertEqual(len(authority.requests), 1)
        self.assertTrue(authority.requests[0].url.path.endswith("ListProjectRoles"))
        query = json.loads(authority.requests[0].content)
        self.assertEqual(query["filters"][0]["roleKeyFilter"]["key"], "moscow")

    def test_two_simultaneous_installers_succeed_with_one_creation(self) -> None:
        authority = RoleAuthority(race=True)

        def onboard(_index: int) -> bool:
            with httpx.Client(transport=httpx.MockTransport(authority.handle)) as client:
                return ZitadelRoleRegistry(self.config(), client).ensure(NodeSpec(node_id="moscow"))

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(onboard, range(2)))
        self.assertCountEqual(statuses, [True, False])
        self.assertEqual(authority.creates, 1)

    def test_invalid_node_ids_and_missing_credentials_are_rejected(self) -> None:
        for value in ("", "Uppercase", "node_1", "node ", "a" * 64, "../node"):
            with self.subTest(node=value), self.assertRaises(ValidationError):
                NodeSpec(node_id=value)
        with self.assertRaises(ValidationError):
            RegistryConfig(
                issuer="https://identity.example.test", project_id="project", token=SecretStr("")
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
                ZitadelRoleRegistry(self.config(), client).ensure(NodeSpec(node_id="moscow"))
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
                ZitadelRoleRegistry(self.config(), client).ensure(NodeSpec(node_id="moscow"))

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
            ZitadelRoleRegistry(self.config(), client).ensure(NodeSpec(node_id="moscow"))
        self.assertEqual(caught.exception.code, ErrorCode.UNCERTAIN)
        self.assertEqual(len(calls), 2)


class EnvironmentNodeStartupContracts(unittest.TestCase):
    def test_environment_drives_role_creation_and_repeat_startup(self) -> None:
        authority = RoleAuthority()
        environment = {
            "BRIAREUS_NODE_ID": "moscow",
            "OIDC_ISSUER_URL": "https://identity.example.test",
            "OIDC_AUDIENCE": "project",
            "OIDC_PROVISIONING_PROVIDER": "zitadel",
            "OIDC_PROVISIONING_TOKEN": TOKEN,
            "CONTROL_PANEL_PUBLIC_BASE_URL": "https://alias.example.test",
        }
        with patch.dict(os.environ, environment, clear=True):
            identity = OidcTokenSettings()
            provisioning = NodeProvisioningSettings()
        for expected in (True, False):
            client = httpx.Client(transport=httpx.MockTransport(authority.handle))
            with patch(
                "control_panel_api.infrastructure.node_registration._startup.httpx.Client",
                return_value=client,
            ):
                self.assertEqual(ensure_node_role(identity, provisioning), expected)
        self.assertEqual(identity.node_id, "moscow")
        self.assertEqual(authority.creates, 1)
        self.assertNotIn(TOKEN, repr(provisioning))

    def test_old_role_setting_does_not_silently_replace_node_identity(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "OIDC_REQUIRED_ROLE": "access",
                    "OIDC_ISSUER_URL": "https://identity.example.test",
                    "OIDC_AUDIENCE": "project",
                },
                clear=True,
            ),
            self.assertRaises(ValueError),
        ):
            OidcTokenSettings().validate_bootstrap()

    def test_provider_failure_prevents_startup_without_exposing_credential(self) -> None:
        identity = OidcTokenSettings(
            issuer_url="https://identity.example.test", audience="project", required_role="moscow"
        )
        provisioning = NodeProvisioningSettings(provider="zitadel", token=SecretStr(TOKEN))
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(403, text=TOKEN),
            )
        )
        with (
            patch(
                "control_panel_api.infrastructure.node_registration._startup.httpx.Client",
                return_value=client,
            ),
            self.assertRaises(NodeRegistrationError) as error,
        ):
            ensure_node_role(identity, provisioning)
        self.assertEqual(error.exception.status, 403)
        self.assertNotIn(TOKEN, str(error.exception))
