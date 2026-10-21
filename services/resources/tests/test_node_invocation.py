"""Critical private context boundary checks with explicit owner-port fixtures.

These do not replace live Rauthy/Cedar/provider acceptance. No working database,
real credential, global provider account or network request is used.
"""
import json
import time
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.requests import Request

from projects.node_invocation import InvocationCommand, invocation_router, project_accounts, selection
from node_protocol.module_effects import resource_id


class InvocationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.project, self.actor, self.node, self.storage, self.connection = (uuid4() for _ in range(5))
        self.cipher = Fernet(Fernet.generate_key())
        self.binding = dict(node_uuid=str(self.node), placement_uuid=str(uuid4()), project_uuid=str(self.project),
            workspace_uuid=str(self.storage), fingerprint="a"*64, resource_revision=2,
            resource_id=resource_id("svc", self.node, self.project, self.storage),
            effect_verify_key="public-fixture-key"*6, expires_at=int(time.time())+5)
        self.command = InvocationCommand(issuer="https://issuer.example/auth/v1/", subject="verified-subject",
            project_uuid=self.project, actor_uuid=self.actor, agent_session_uuid=uuid4(), grant_revision=3,
            identity_expires_at=datetime.now(UTC)+timedelta(seconds=15), module="svc", tool="github_accounts",
            arguments={}, binding=self.binding)
        now = datetime.now(UTC)
        self.row = SimpleNamespace(id=self.connection, alias="project-account", provider="github", auth_type="github_token",
            provider_settings={"base_url":"https://api.github.com"}, owner_project_id=self.project,
            owner_team_id=None, deleted_at=None, created_at=now, updated_at=now,
            encrypted_credential=self.encrypt(self.project))

    def encrypt(self, project):
        return self.cipher.encrypt(json.dumps({"connection":str(self.connection), "project":str(project),
            "token":"fixture-private-provider-value"}).encode()).decode()

    def database(self, rows=None):
        owner = self
        class Database:
            @asynccontextmanager
            async def transaction(self):
                yield self
            async def scalars(self, statement):
                # Assert the actual query binds the selected project/provider;
                # the returned rows are explicit fixtures, not SQL acceptance.
                values = statement.compile().params.values()
                owner.assertIn(owner.project, values)
                return SimpleNamespace(all=lambda: rows if rows is not None else [owner.row])
        return Database()

    async def test_account_listing_never_decrypts_or_returns_credentials(self):
        class NoDecrypt:
            def decrypt(self, _):
                raise AssertionError("Metadata account listing must not read a credential")
        context = await project_accounts(self.database(), NoDecrypt(), self.command)
        self.assertEqual(context["accounts"][0]["id"], str(self.connection))
        self.assertNotIn("credential", context["accounts"][0])

    async def test_one_selected_project_credential_keeps_exact_owner_binding(self):
        command = self.command.model_copy(update={"tool":"github_profile", "arguments":{"account_id":"project-account"}})
        context = await project_accounts(self.database(), self.cipher, command)
        self.assertEqual(context["accounts"][0]["credential"], "fixture-private-provider-value")
        self.row.encrypted_credential = self.encrypt(uuid4())
        with self.assertRaises(ValueError):
            await project_accounts(self.database(), self.cipher, command)

    async def test_selected_connection_policy_refreshed_and_not_shared_between_accounts(self):
        command = self.command.model_copy(update={"tool":"github_profile", "arguments":{"account_id":"project-account"}})
        self.row.provider_settings["git_policy"] = {"protected_branches":["release"],
            "required_checks":["ci"], "required_reviewers":["owner"], "local_git_transport_enabled":False}
        context = await project_accounts(self.database(), self.cipher, command)
        self.assertEqual(context["policies"]["github"]["required_checks"], ["ci"])
        self.assertFalse(context["policies"]["github_runtime"]["local_git_transport_enabled"])
        self.assertNotIn("gitlab", context["policies"])
        self.row.provider_settings["git_policy"] = {"remote_source_mutations_enabled":True}
        changed = await project_accounts(self.database(), self.cipher, command)
        self.assertTrue(changed["policies"]["github_runtime"]["remote_source_mutations_enabled"])
        self.assertTrue(changed["policies"]["github_runtime"]["local_git_transport_enabled"])

    async def test_foreign_deleted_team_or_ambiguous_account_is_rejected(self):
        command = self.command.model_copy(update={"tool":"github_profile", "arguments":{"account_id":"project-account"}})
        for fields in ({"owner_project_id":uuid4()}, {"owner_team_id":uuid4()}, {"deleted_at":datetime.now(UTC)}):
            old = vars(self.row).copy()
            for key, value in fields.items():
                setattr(self.row, key, value)
            with self.assertRaises(HTTPException):
                await project_accounts(self.database(), self.cipher, command)
            self.row = SimpleNamespace(**old)
        with self.assertRaises(HTTPException):
            await project_accounts(self.database([self.row, self.row]), self.cipher, command)

    async def test_provider_choice_is_bounded_and_never_reuses_another_provider(self):
        self.assertEqual(selection("svc", "accounts", {}), ("gitlab", None))
        self.assertEqual(selection("svc", "github_accounts", {}), ("github", None))
        self.assertEqual(selection("infrastructure", "observability_search_logs", {"account_id":"one"}), ("signoz", "one"))
        self.assertEqual(selection("infrastructure", "observability_get_deployment", {"account_id":"one", "uuid":"deployment"}), ("coolify", "one"))
        with self.assertRaises(ValueError):
            selection("infrastructure", "observability_connection", {"provider":"github", "account_id":"one"})

    async def test_deferred_provider_selection_keeps_exact_account_and_provider(self):
        self.assertEqual(selection("svc", "svc_operation_start", {"tool":"github_agent_list_issues",
            "arguments":{"account_id":"selected", "repository":"owner/repo"}}), ("github", "selected"))
        self.assertEqual(selection("svc", "svc_operation_poll", {"operation_id":"opaque", "tool":"github_agent_list_issues",
            "account_id":"selected"}), ("github", "selected"))
        self.assertEqual(selection("svc", "svc_operation_poll", {"operation_id":"opaque", "tool":"github_accounts"}), ("github", None))
        with self.assertRaises(ValueError):
            selection("svc", "svc_operation_poll", {"operation_id":"opaque", "tool":"github_agent_list_issues"})
        with self.assertRaises(ValueError):
            selection("svc", "svc_operation_start", {"tool":"svc_operation_poll", "arguments":{}})
        self.assertEqual(selection("infrastructure", "infrastructure_operation_poll", {"operation_id":"opaque",
            "tool":"observability_get_deployment", "account_id":"coolify-selected"}), ("coolify", "coolify-selected"))
        self.assertEqual(selection("infrastructure", "infrastructure_operation_poll", {"operation_id":"opaque",
            "tool":"observability_connection", "account_id":"signoz-selected", "provider":"signoz"}), ("signoz", "signoz-selected"))

    async def test_wrong_peer_and_revoked_membership_never_query_account_storage(self):
        owner = self
        class Platform:
            async def call(self, *_):
                return 403, {}
        async def binding(*_):
            owner.fail("Revoked membership must not resolve a placement")
        def database():
            owner.fail("Unauthorized invocation must not query account storage")
        endpoint = invocation_router(platform=Platform(), cipher=self.cipher,
            resolve_database=database, resolve_binding=binding).routes[0].endpoint
        payload = self.command.model_dump_json().encode()
        async def receive():
            return {"type":"http.request", "body":payload, "more_body":False}
        for peer in ("briareus:gateway", "briareus:control-panel-api", "briareus:authorization"):
            with self.assertRaises(HTTPException) as error:
                await endpoint(Request({"type":"http", "headers":[], "briareus.service_peer":peer}, receive))
            self.assertEqual(error.exception.status_code, 403)

    async def test_current_identity_and_placement_bound_private_reply(self):
        owner = self
        permissions = ["use_resources"]
        selected = self.command.binding

        class Platform:
            async def call(self, path, value):
                owner.assertEqual(path, "/internal/v1/platform/oidc/actor-context")
                return 200, {"issuer":owner.command.issuer, "subject":owner.command.subject,
                    "actor_uuid":str(owner.actor), "project_uuid":str(owner.project), "permissions":permissions,
                    "expires_at":(datetime.now(UTC)+timedelta(seconds=15)).isoformat()}

        async def binding(project, module, request):
            owner.assertEqual((project, module), (owner.project, "svc"))
            return selected

        endpoint = invocation_router(platform=Platform(), cipher=self.cipher,
            resolve_database=self.database, resolve_binding=binding).routes[0].endpoint
        async def receive():
            return {"type":"http.request", "body":owner.command.model_dump_json().encode(), "more_body":False}
        def request():
            return Request({"type":"http", "headers":[], "briareus.service_peer":"briareus:authorization"}, receive)
        reply = await endpoint(request())
        value = json.loads(reply.body)
        self.assertEqual(set(value), {"context", "expires_at"})
        self.assertLessEqual(value["expires_at"], self.command.binding.expires_at)
        self.assertNotIn("credential", value["context"]["accounts"][0])
        selected = selected.model_copy(update={"placement_uuid":uuid4()})
        with self.assertRaises(HTTPException) as error:
            await endpoint(request())
        self.assertEqual(error.exception.status_code, 403)
        permissions = "use_resources"  # A string is not a typed permission set.
        with self.assertRaises(HTTPException) as error:
            await endpoint(request())
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
