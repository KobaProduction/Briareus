"""Runtime overrides are independent from short authority leases."""

import unittest
from collections.abc import AsyncIterator, Callable
from unittest.mock import patch
from uuid import uuid4

from fastapi.routing import APIRoute
from projects.domain.runtime_settings import RuntimeOverride, RuntimeOverrides, RuntimeSetting
from projects.node_management import NodeManagementBoundary
from projects.runtime_policy import resolve_policy

from common.owner_migrations import owner_config
from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from node_protocol import ModuleRelease, ResourceLimits
from node_protocol.grpc_codec import decode_deployment, encode_deployment
from node_protocol.models import (
    Deployment,
    ModuleConfiguration,
    RuntimePolicy,
    RuntimePolicyOverrides,
)
from runtime_peer import PeerClient, VerifiedOwnerReply


class RuntimePolicyTests(unittest.TestCase):
    def test_defaults_inheritance_and_explicit_disable(self) -> None:
        policy, sources = resolve_policy()
        self.assertIsNone(policy.execution_timeout_seconds)
        self.assertEqual(policy.web_max_tabs, 10)
        policy, sources = resolve_policy(
            RuntimeOverrides(
                (
                    RuntimeOverride(RuntimeSetting.EXECUTION_TIMEOUT, 90),
                    RuntimeOverride(RuntimeSetting.WEB_MAX_TABS, 4),
                    RuntimeOverride(RuntimeSetting.TERMINAL_IDLE, 30),
                )
            ),
            RuntimeOverrides(
                (
                    RuntimeOverride(RuntimeSetting.EXECUTION_TIMEOUT, None),
                    RuntimeOverride(RuntimeSetting.WEB_MAX_TABS, 12),
                )
            ),
        )
        self.assertIsNone(policy.execution_timeout_seconds)
        self.assertEqual(policy.web_max_tabs, 12)
        self.assertEqual(policy.terminal_idle_seconds, 30)
        self.assertEqual(sources["execution_timeout_seconds"], "node")
        self.assertEqual(sources["terminal_idle_seconds"], "server")

    def test_override_serialization_preserves_inheritance(self) -> None:
        from pydantic import BaseModel

        class Wrapper(BaseModel):
            policy: RuntimePolicyOverrides

        wire = Wrapper(policy=RuntimePolicyOverrides(web_max_tabs=None)).model_dump(mode="json")
        self.assertEqual(wire, {"policy": {"web_max_tabs": None}})

    def test_typed_protobuf_preserves_nullable_policy(self) -> None:
        spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            release=ModuleRelease(
                module="svc", lifecycle="sessionful", image="localhost:5500/svc@sha256:" + "a" * 64
            ),
            limits=ResourceLimits(memory_bytes=1024**3, cpu_millis=1000, pids=128),
            configuration=ModuleConfiguration(
                runtime_policy=RuntimePolicy(web_max_tabs=None, execution_timeout_seconds=7)
            ),
        )
        decoded = decode_deployment(encode_deployment(spec))
        self.assertEqual(decoded, spec)
        self.assertEqual(decoded.fingerprint, spec.fingerprint)

    def test_missing_policy_keeps_legacy_wire(self) -> None:
        self.assertNotIn("runtime_policy", ModuleConfiguration().model_dump())

    def test_reviewed_additive_migration_graph(self) -> None:
        location = owner_config("resources").get_main_option("script_location")
        assert location is not None
        self.assertEqual(
            location.replace("\\", "/").split("/")[-1],
            "migrations",
        )


class RuntimePolicyRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_node_command_fields_and_server_read_route(self) -> None:
        import json
        from contextlib import asynccontextmanager
        from datetime import UTC, datetime, timedelta

        from cryptography.fernet import Fernet
        from fastapi import Request
        from projects.node_management import NodeCommand, NodeRegistration, node_router
        from sqlalchemy import Select
        from sqlalchemy.sql.elements import TextClause

        self.assertTrue(
            {"policy_scope", "policy_values", "expected_policy_sequence"}
            <= set(NodeCommand.model_fields)
        )
        self.assertFalse(
            {"policy_scope", "policy_values", "expected_policy_sequence"}
            & set(NodeRegistration.model_fields)
        )
        actor, project = uuid4(), uuid4()
        expiry = datetime.now(UTC) + timedelta(seconds=15)
        command = NodeCommand(
            issuer="https://provider.example",
            subject="fixture",
            actor_uuid=actor,
            project_uuid=project,
            operation_uuid=uuid4(),
            identity_expires_at=expiry,
            action="runtime_policy_get",
            policy_scope="server",
        )

        class Platform(PeerClient):
            def __init__(self) -> None:
                pass

            async def call[ReplyT](
                self, path: str, wire: dict[str, object], *, decode: Callable[[int, object], ReplyT]
            ) -> VerifiedOwnerReply[ReplyT]:
                if path != "/internal/v1/platform/oidc/actor-context":
                    raise AssertionError("Current Platform proof required")
                return VerifiedOwnerReply(
                    200,
                    decode(
                        200,
                        {
                            "issuer": wire["issuer"],
                            "subject": wire["subject"],
                            "actor_uuid": str(actor),
                            "project_uuid": str(project),
                            "role": "operator",
                            "permissions": ["use_resources"],
                            "expires_at": expiry.isoformat(),
                        },
                    ),
                )

        class Tx:
            async def execute(self, statement: TextClause, parameters: dict[str, str]) -> None:
                if (
                    "pg_advisory_xact_lock" not in str(statement)
                    or parameters["key"] != "runtime-policy:server"
                ):
                    raise AssertionError("Canonical runtime scope must be locked")

            async def get[RowT](self, _model: type[RowT], _key: object) -> RowT | None:
                return None

            async def scalar[RowT](self, _query: Select[tuple[RowT]]) -> RowT | None:
                return None

        database = PlatformDatabase(
            PlatformDatabaseSettings.model_validate(
                {
                    "POSTGRES_HOST": "127.0.0.1",
                    "POSTGRES_PORT": 1,
                    "POSTGRES_DB": "briareus_resources",
                    "POSTGRES_USER": "fixture",
                    "POSTGRES_PASSWORD": uuid4().hex,
                }
            )
        )
        self.addAsyncCleanup(database.close)

        @asynccontextmanager
        async def transaction() -> AsyncIterator[Tx]:
            yield Tx()

        self.enterContext(patch.object(database, "transaction", transaction))

        router = node_router(
            platform=Platform(),
            resolve_database=lambda: database,
            cipher=Fernet(Fernet.generate_key()),
        )
        try:
            route = router.routes[0]
            assert isinstance(route, APIRoute)
            boundary: object = getattr(route.endpoint, "__self__", None)
            assert isinstance(boundary, NodeManagementBoundary)
            reply = await boundary.nodes(
                command,
                Request({"type": "http", "briareus.service_peer": "briareus:control-panel-api"}),
            )
            value = json.loads(bytes(reply.body))["runtime_policy"]
            self.assertEqual(value["sequence"], 0)
            self.assertIsNone(value["effective"]["execution_timeout_seconds"])
            self.assertEqual(value["effective"]["web_max_tabs"], 10)
        finally:
            await router.node_placements.close()
