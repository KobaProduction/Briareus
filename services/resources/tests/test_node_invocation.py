"""Private custody boundaries with real codecs and SQL adapters, without provider IO."""

from __future__ import annotations

import json
import time
import unittest
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.routing import APIRoute
from projects.domain.node_invocation import ProviderModule, ProviderSelection, select_provider
from projects.domain.provider_connections import ConnectionFailure
from projects.infrastructure.connection_metadata import StoredConnectionSettings
from projects.node_invocation import InvocationCommand, invocation_router, project_accounts
from projects.presentation.node_invocation import NodeInvocationBoundary
from sqlalchemy import Select
from starlette.requests import Request
from starlette.types import Message

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from node_protocol.effect import NodeWorkspaceBinding
from node_protocol.module_effects import resource_id
from projects._resource_persistence import IntegrationRow
from runtime_peer import PeerClient, VerifiedOwnerReply
from runtime_peer.connection_contracts import GitPolicyForm


class InvocationPlatform(PeerClient):
    def __init__(self, owner: InvocationTests) -> None:
        self.test = owner
        self.revoked = False
        self.malformed_permissions = False

    async def call[ReplyT](
        self, path: str, payload: dict[str, object], *, decode: Callable[[int, object], ReplyT]
    ) -> VerifiedOwnerReply[ReplyT]:
        self.test.assertEqual(path, "/internal/v1/platform/oidc/actor-context")
        self.test.assertEqual(payload["project_uuid"], str(self.test.project))
        if self.revoked:
            return VerifiedOwnerReply(403, decode(403, {}))
        wire = {
            "issuer": self.test.command.issuer,
            "subject": self.test.command.subject,
            "actor_uuid": str(self.test.actor),
            "project_uuid": str(self.test.project),
            "role": "user",
            "permissions": "use_resources" if self.malformed_permissions else ["use_resources"],
            "expires_at": (datetime.now(UTC) + timedelta(seconds=15)).isoformat(),
        }
        return VerifiedOwnerReply(200, decode(200, wire))


class InvocationSQL:
    def __init__(self, owner: InvocationTests, rows: tuple[IntegrationRow, ...]) -> None:
        self.test, self.rows = owner, rows

    async def scalars(self, statement: Select[tuple[IntegrationRow]]) -> tuple[IntegrationRow, ...]:
        self.test.assertIn(self.test.project, statement.compile().params.values())
        if self.test.forbid_storage:
            raise AssertionError("Unauthorized invocation must not query account storage")
        return self.rows


class InvocationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project, self.actor, self.node, self.storage, self.connection = (
            uuid4() for _ in range(5)
        )
        self.cipher = Fernet(Fernet.generate_key())
        self.binding = NodeWorkspaceBinding(
            node_uuid=self.node,
            placement_uuid=uuid4(),
            project_uuid=self.project,
            workspace_uuid=self.storage,
            fingerprint="a" * 64,
            resource_revision=2,
            resource_id=resource_id("svc", self.node, self.project, self.storage),
            effect_verify_key="public-fixture-key" * 6,
            expires_at=int(time.time()) + 5,
        )
        self.command = InvocationCommand.model_validate(
            {
                "issuer": "https://issuer.example/auth/v1/",
                "subject": "verified-subject",
                "project_uuid": self.project,
                "actor_uuid": self.actor,
                "agent_session_uuid": uuid4(),
                "grant_revision": 3,
                "identity_expires_at": datetime.now(UTC) + timedelta(seconds=15),
                "module": "svc",
                "tool": "github_accounts",
                "arguments": {},
                "binding": self.binding,
            }
        )
        self.row = self.account_row()
        self.selected = self.binding
        self.forbid_storage = False
        self.platform = InvocationPlatform(self)

    def account_row(
        self,
        *,
        project: UUID | None = None,
        team: UUID | None = None,
        deleted_at: datetime | None = None,
    ) -> IntegrationRow:
        now = datetime.now(UTC)
        return IntegrationRow(
            id=self.connection,
            alias="project-account",
            alias_key="project-account",
            provider="github",
            auth_type="github_token",
            provider_settings=StoredConnectionSettings(base_url="https://api.github.com"),
            owner_project_id=project or self.project,
            owner_team_id=team,
            deleted_at=deleted_at,
            created_at=now,
            updated_at=now,
            encrypted_credential=self.encrypt(self.project),
        )

    def encrypt(self, project: UUID) -> str:
        return self.cipher.encrypt(
            json.dumps(
                {
                    "connection": str(self.connection),
                    "project": str(project),
                    "token": "fixture-private-provider-value",
                }
            ).encode()
        ).decode()

    def database(self, rows: tuple[IntegrationRow, ...] | None = None) -> PlatformDatabase:
        database = PlatformDatabase(
            PlatformDatabaseSettings.model_validate(
                {
                    "POSTGRES_HOST": "127.0.0.1",
                    "POSTGRES_PORT": 1,
                    "POSTGRES_DB": "briareus_resources",
                    "POSTGRES_USER": "unused_fixture",
                    "POSTGRES_PASSWORD": uuid4().hex,
                }
            )
        )

        @asynccontextmanager
        async def transaction() -> AsyncIterator[InvocationSQL]:
            yield InvocationSQL(self, (self.row,) if rows is None else rows)

        replacement = patch.object(database, "transaction", transaction)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.addAsyncCleanup(database.close)
        return database

    def invocation(
        self, tool: str, arguments: dict[str, object], *, module: ProviderModule = "svc"
    ) -> InvocationCommand:
        return InvocationCommand.model_validate(
            {
                **self.command.model_dump(exclude={"arguments"}),
                "module": module,
                "tool": tool,
                "arguments": arguments,
            }
        )

    def selected_provider(
        self, module: ProviderModule, tool: str, arguments: dict[str, object]
    ) -> ProviderSelection:
        return select_provider(module, self.invocation(tool, arguments, module=module).arguments)

    async def test_account_listing_never_decrypts_or_returns_credentials(self) -> None:
        with patch.object(self.cipher, "decrypt", side_effect=AssertionError("No credential read")):
            context = await project_accounts(self.database(), self.cipher, self.command)
        self.assertEqual(context.accounts[0].id, self.connection)
        self.assertNotIn("credential", context.accounts[0].model_dump(exclude_unset=True))

    async def test_one_selected_project_credential_keeps_exact_owner_binding(self) -> None:
        command = self.invocation("github_profile", {"account_id": "project-account"})
        database = self.database()
        context = await project_accounts(database, self.cipher, command)
        self.assertEqual(context.accounts[0].credential, "fixture-private-provider-value")
        self.row.encrypted_credential = self.encrypt(uuid4())
        with self.assertRaises(ValueError):
            await project_accounts(database, self.cipher, command)

    async def test_selected_connection_policy_refreshed_and_not_shared_between_accounts(
        self,
    ) -> None:
        command = self.invocation("github_profile", {"account_id": "project-account"})
        self.row.provider_settings = StoredConnectionSettings(
            base_url="https://api.github.com",
            git_policy=GitPolicyForm(
                protected_branches=["release"],
                required_checks=["ci"],
                required_reviewers=["owner"],
                local_git_transport_enabled=False,
            ),
        )
        database = self.database()
        context = await project_accounts(database, self.cipher, command)
        assert context.policies is not None and context.policies.github is not None
        assert context.policies.github_runtime is not None
        self.assertEqual(context.policies.github.required_checks, ["ci"])
        self.assertFalse(context.policies.github_runtime.local_git_transport_enabled)
        self.assertIsNone(context.policies.gitlab)
        self.row.provider_settings = StoredConnectionSettings(
            base_url="https://api.github.com",
            git_policy=GitPolicyForm(remote_source_mutations_enabled=True),
        )
        changed = await project_accounts(database, self.cipher, command)
        assert changed.policies is not None and changed.policies.github_runtime is not None
        self.assertTrue(changed.policies.github_runtime.remote_source_mutations_enabled)
        self.assertTrue(changed.policies.github_runtime.local_git_transport_enabled)

    async def test_foreign_deleted_team_or_ambiguous_account_is_rejected(self) -> None:
        command = self.invocation("github_profile", {"account_id": "project-account"})
        for row in (
            self.account_row(project=uuid4()),
            self.account_row(team=uuid4()),
            self.account_row(deleted_at=datetime.now(UTC)),
        ):
            with self.assertRaises(ConnectionFailure):
                await project_accounts(self.database((row,)), self.cipher, command)
        with self.assertRaises(ConnectionFailure):
            await project_accounts(self.database((self.row, self.row)), self.cipher, command)

    async def test_provider_choice_is_bounded_and_never_reuses_another_provider(self) -> None:
        self.assertEqual(self.selected_provider("svc", "accounts", {}), ("gitlab", None))
        self.assertEqual(self.selected_provider("svc", "github_accounts", {}), ("github", None))
        self.assertEqual(
            self.selected_provider(
                "infrastructure", "observability_search_logs", {"account_id": "one"}
            ),
            ("signoz", "one"),
        )
        self.assertEqual(
            self.selected_provider(
                "infrastructure",
                "observability_get_deployment",
                {"account_id": "one", "uuid": "deployment"},
            ),
            ("coolify", "one"),
        )
        with self.assertRaises(ValueError):
            self.selected_provider(
                "infrastructure",
                "observability_connection",
                {"provider": "github", "account_id": "one"},
            )

    async def test_deferred_provider_selection_keeps_exact_account_and_provider(self) -> None:
        self.assertEqual(
            self.selected_provider(
                "svc",
                "svc_operation_start",
                {
                    "tool": "github_agent_list_issues",
                    "arguments": {"account_id": "selected", "repository": "owner/repo"},
                },
            ),
            ("github", "selected"),
        )
        self.assertEqual(
            self.selected_provider(
                "svc",
                "svc_operation_poll",
                {
                    "operation_id": "opaque",
                    "tool": "github_agent_list_issues",
                    "account_id": "selected",
                },
            ),
            ("github", "selected"),
        )
        self.assertEqual(
            self.selected_provider(
                "svc", "svc_operation_poll", {"operation_id": "opaque", "tool": "github_accounts"}
            ),
            ("github", None),
        )
        with self.assertRaises(ValueError):
            self.selected_provider(
                "svc",
                "svc_operation_poll",
                {"operation_id": "opaque", "tool": "github_agent_list_issues"},
            )
        with self.assertRaises(ValueError):
            self.selected_provider(
                "svc", "svc_operation_start", {"tool": "svc_operation_poll", "arguments": {}}
            )
        self.assertEqual(
            self.selected_provider(
                "infrastructure",
                "infrastructure_operation_poll",
                {
                    "operation_id": "opaque",
                    "tool": "observability_get_deployment",
                    "account_id": "coolify-selected",
                },
            ),
            ("coolify", "coolify-selected"),
        )
        self.assertEqual(
            self.selected_provider(
                "infrastructure",
                "infrastructure_operation_poll",
                {
                    "operation_id": "opaque",
                    "tool": "observability_connection",
                    "account_id": "signoz-selected",
                    "provider": "signoz",
                },
            ),
            ("signoz", "signoz-selected"),
        )

    def boundary(self) -> NodeInvocationBoundary:
        database = self.database()

        async def binding(project: UUID, module: str, _request: Request) -> NodeWorkspaceBinding:
            self.assertEqual((project, module), (self.project, "svc"))
            if self.platform.revoked:
                raise AssertionError("Revoked membership must not resolve a placement")
            return self.selected

        router = invocation_router(
            platform=self.platform,
            cipher=self.cipher,
            resolve_database=lambda: database,
            resolve_binding=binding,
        )
        for route in router.routes:
            if isinstance(route, APIRoute):
                controller: object = getattr(route.endpoint, "__self__", None)
                if isinstance(controller, NodeInvocationBoundary):
                    return controller
        raise AssertionError("Private invocation route must bind its real controller")

    def request(self, peer: str = "briareus:authorization") -> Request:
        raw = json.dumps(
            {**self.command.model_dump(mode="json", exclude={"arguments"}), "arguments": {}}
        ).encode()

        async def receive() -> Message:
            return {"type": "http.request", "body": raw, "more_body": False}

        return Request({"type": "http", "headers": [], "briareus.service_peer": peer}, receive)

    async def test_wrong_peer_and_revoked_membership_never_query_account_storage(self) -> None:
        self.platform.revoked = True
        self.forbid_storage = True
        boundary = self.boundary()
        for peer in ("briareus:gateway", "briareus:control-panel-api", "briareus:authorization"):
            with self.assertRaises(HTTPException) as error:
                await boundary.invoke(self.request(peer))
            self.assertEqual(error.exception.status_code, 403)

    async def test_current_identity_and_placement_bound_private_reply(self) -> None:
        boundary = self.boundary()
        reply = await boundary.invoke(self.request())
        value = json.loads(bytes(reply.body))
        self.assertEqual(set(value), {"context", "expires_at"})
        self.assertLessEqual(value["expires_at"], self.binding.expires_at)
        self.assertNotIn("credential", value["context"]["accounts"][0])
        self.selected = self.binding.model_copy(update={"placement_uuid": uuid4()})
        with self.assertRaises(HTTPException) as error:
            await boundary.invoke(self.request())
        self.assertEqual(error.exception.status_code, 403)
        self.selected = self.binding
        self.platform.malformed_permissions = True
        with self.assertRaises(HTTPException) as error:
            await boundary.invoke(self.request())
        self.assertEqual(error.exception.status_code, 403)
