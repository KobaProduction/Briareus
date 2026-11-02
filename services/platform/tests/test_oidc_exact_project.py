"""Real PostgreSQL selectors and signed-peer fixtures across two ASGI owners."""

from __future__ import annotations

import hashlib
import unittest
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from itertools import pairwise
from pathlib import Path
from typing import Literal, NamedTuple
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from control_panel_api._oidc_browser import OidcBrowserSessionStore
from control_panel_api._oidc_membership import platform_membership_router
from control_panel_api._platform_current_client import (
    PrivatePlatformCurrentClient,
    VerifiedPanelDelegation,
    VerifiedPlatformServiceTransport,
)
from control_panel_api.application.approval_contracts import (
    ApprovalManagementPort,
    CurrentSessionSnapshot,
)
from control_panel_api.domain.platform_authority import PanelOidcSession
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from postgres_fixture import PostgresOwnerFixture
from projects._oidc_access_project_api import (
    AccessMembershipQuery,
    VerifiedAccessProjectPeer,
    oidc_access_project_router,
)
from projects._oidc_context_api import (
    PlatformContextQuery,
    VerifiedPanelContextPeer,
    current_platform_context_router,
)
from projects._oidc_membership_projection import (
    CurrentRauthyPlatformMembership,
    CurrentRauthyUserLink,
    PlatformOidcMembershipProjection,
    PlatformSubjectLinkUnavailable,
)
from projects._rauthy_first_operator import (
    FirstOperatorBootstrap,
    FirstOperatorBootstrapDenied,
    FirstOperatorBootstrapUnavailable,
    VerifiedFirstOperatorApproval,
)
from projects._rauthy_user_links import VerifiedRauthyUserStatus
from projects.domain.user_links import canonical_subject
from pydantic import SecretStr, TypeAdapter
from sqlalchemy import Table, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.sql import Select

from common.owner_migrations import (
    _NEW_EPOCH_SOURCE_HASHES,
    OwnerSchemaRejected,
    _ddl_source,
    _migration_directory,
    _require_owner_revision_epoch,
    _upgrade_owner,
    owner_config,
)
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from projects._persistence import ProjectRow
from teams._persistence import TeamMembershipRow, TeamRow

_ISSUER = "https://briareus.koba-nexus.ru/auth/v1/"
_ORIGIN = "https://briareus.koba-nexus.ru"
_COOKIE = "source-only-browser-" + "A" * 40
_SUBJECT = "R" * 24


def deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=20)


class UserLinkFixture:
    def __init__(self, actor: UUID) -> None:
        self.current = CurrentRauthyUserLink(_ISSUER, _SUBJECT, actor, True, "user", 1, deadline())

    async def current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        if issuer != self.current.issuer or subject != self.current.subject:
            return None
        return self.current


class PanelPeerFixture:
    def __init__(self, client: AsyncClient) -> None:
        self.client = client
        self.scope: UUID | None = None
        self.signed: VerifiedPanelDelegation | None = None
        self.bad_scope = False
        self.expires_at = deadline()

    async def current_transport(self) -> VerifiedPlatformServiceTransport:
        self.expires_at = deadline()
        return VerifiedPlatformServiceTransport(
            self.client, "unix-peer", "briareus:platform", self.expires_at
        )

    async def signed_subject_delegation(
        self, *, issuer: str, subject: str
    ) -> VerifiedPanelDelegation:
        return await self._delegate(issuer, subject, None)

    async def signed_project_delegation(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> VerifiedPanelDelegation:
        return await self._delegate(issuer, subject, project_uuid)

    async def _delegate(
        self, issuer: str, subject: str, project: UUID | None
    ) -> VerifiedPanelDelegation:
        self.scope = uuid4() if self.bad_scope else project
        self.signed = VerifiedPanelDelegation(
            SecretStr("fixture-scope-proof-" + "X" * 48),
            subject,
            issuer,
            "briareus:platform",
            self.expires_at,
            self.scope,
        )
        return self.signed

    async def verify(
        self, request: Request, query: PlatformContextQuery
    ) -> VerifiedPanelContextPeer:
        assert request.headers["authorization"].startswith("Bearer fixture-")
        assert query.issuer == _ISSUER and query.subject == _SUBJECT
        assert self.signed is not None
        return VerifiedPanelContextPeer(
            "briareus:platform",
            "control-panel-api",
            _ISSUER,
            _SUBJECT,
            self.expires_at,
            self.scope,
        )


class BrowserFixture:
    async def get_session(self, token: str) -> PanelOidcSession | None:
        if token == _COOKIE:
            return PanelOidcSession(_ISSUER, _SUBJECT, "briareus-control-panel", deadline())
        return None


def bootstrap_approval() -> VerifiedFirstOperatorApproval:
    return VerifiedFirstOperatorApproval(
        uuid4(),
        uuid4(),
        _ISSUER,
        _SUBJECT,
        "briareus:platform:first-operator",
        True,
        True,
        uuid4(),
        "fixture project",
        deadline(),
    )


def bootstrap_database(
    session: AsyncSession,
    after_commit: Callable[[], None] | None = None,
) -> PlatformDatabase:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[AsyncSession]:
        yield session
        if after_commit is not None:
            after_commit()

    database = Mock(spec=PlatformDatabase)
    database.engine = Mock(spec=AsyncEngine)
    database.engine.url.database = "briareus_platform"
    database.transaction = Mock(side_effect=transaction)
    return database


class BootstrapBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_operator_rejects_foreign_issuer_and_noncanonical_subject(self) -> None:
        approval = bootstrap_approval()
        database = Mock(spec=PlatformDatabase)
        database.engine = Mock(spec=AsyncEngine)
        database.engine.url.database = "briareus_platform"
        database.transaction.side_effect = AssertionError("unverified operator reached SQL")
        status = Mock()
        status.current_status = AsyncMock(side_effect=ValueError("No provider evidence"))
        cases: tuple[tuple[str, str | int], ...] = (
            ("https://foreign.invalid/auth/v1/", _SUBJECT),
            (_ISSUER, "invalid/subject"),
            (_ISSUER, "Q" * 25),
            (_ISSUER, "Q" * 23),
            (_ISSUER, "\N{FULLWIDTH LATIN CAPITAL LETTER A}" * 24),
            (_ISSUER, 24),
        )
        for issuer, subject in cases:
            with self.subTest(issuer=issuer, subject=subject):
                authority = Mock()
                if isinstance(subject, str):
                    authority.verify = AsyncMock(
                        return_value=replace(
                            approval,
                            rauthy_issuer=issuer,
                            rauthy_subject=subject,
                        )
                    )
                else:
                    self.assertFalse(canonical_subject(subject))
                    authority.verify = AsyncMock(side_effect=ValueError("nontext provider subject"))
                bootstrap = FirstOperatorBootstrap(
                    database=database,
                    authority=authority,
                    rauthy_status=status,
                )
                with self.assertRaises(FirstOperatorBootstrapDenied):
                    await bootstrap.enroll_once(signed_evidence="synthetic")
        status.current_status.assert_not_awaited()
        authority = Mock()
        authority.verify = AsyncMock(
            return_value=replace(
                approval,
                rauthy_issuer="https://localhost:18444/auth/v1/",
            )
        )
        local = FirstOperatorBootstrap(
            database=database,
            authority=authority,
            rauthy_status=status,
        )
        with self.assertRaises(FirstOperatorBootstrapUnavailable):
            await local.enroll_once(signed_evidence="synthetic")
        status.current_status.assert_awaited_once()
        database.transaction.assert_not_called()

    async def test_first_operator_requires_all_platform_tables_empty(self) -> None:
        approval = bootstrap_approval()
        queried: list[str] = []

        def present(query: Select[tuple[int]]) -> int | None:
            table = query.get_final_froms()[0]
            assert isinstance(table, Table)
            queried.append(table.fullname)
            return 1 if table.fullname == "control.audit" else None

        session = AsyncMock(spec=AsyncSession)
        session.scalar.side_effect = present
        authority = Mock()
        authority.verify = AsyncMock(return_value=approval)
        status = Mock()
        status.current_status = AsyncMock(
            return_value=VerifiedRauthyUserStatus(
                _ISSUER,
                _SUBJECT,
                True,
                approval.expires_at,
            )
        )
        bootstrap = FirstOperatorBootstrap(
            database=bootstrap_database(session),
            authority=authority,
            rauthy_status=status,
        )
        with self.assertRaises(FirstOperatorBootstrapDenied):
            await bootstrap.enroll_once(signed_evidence="signed-test-only")
        self.assertIn("control.audit", queried)
        self.assertEqual(len(set(queried)), len(queried))
        session.add.assert_not_called()

    async def test_first_operator_commit_timeout_must_not_acknowledge_privilege(self) -> None:
        import projects._rauthy_first_operator as first_operator_module

        before = datetime.now(UTC)
        instant = [before]
        committed: list[bool] = []
        approval = replace(bootstrap_approval(), expires_at=before + timedelta(seconds=18))

        class Clock:
            @staticmethod
            def now(_tz: tzinfo | None = None) -> datetime:
                return instant[0]

        def after_commit() -> None:
            committed.append(True)
            instant[0] = before + timedelta(seconds=20)

        session = AsyncMock(spec=AsyncSession)
        session.scalar.return_value = None
        authority = Mock()
        authority.verify = AsyncMock(return_value=approval)
        status = Mock()
        status.current_status = AsyncMock(
            return_value=VerifiedRauthyUserStatus(
                _ISSUER,
                _SUBJECT,
                True,
                approval.expires_at,
            )
        )
        bootstrap = FirstOperatorBootstrap(
            database=bootstrap_database(session, after_commit),
            authority=authority,
            rauthy_status=status,
        )
        with (
            patch.object(first_operator_module, "datetime", Clock),
            self.assertRaises(FirstOperatorBootstrapUnavailable),
        ):
            await bootstrap.enroll_once(signed_evidence="signed-test-only")
        self.assertEqual(committed, [True])
        session.flush.assert_awaited_once()
        self.assertEqual(session.add.call_count, 6)


class ExactProjectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.actor = uuid4()
        self.links = UserLinkFixture(self.actor)
        self.db = PostgresOwnerFixture()
        await self.db.initialize()
        self.projection = PlatformOidcMembershipProjection(
            database=self.db, subject_links=self.links
        )
        self.target = uuid4()
        self.team = uuid4()
        other_teams = tuple(uuid4() for _ in range(105))
        async with self.db.transaction() as session:
            for team_id in other_teams:
                session.add(TeamRow(id=team_id, name="fixture", owner_user_id=uuid4()))
            session.add(TeamRow(id=self.team, name="selected", owner_user_id=self.actor))
            await session.flush()
            for team_id in other_teams:
                session.add(TeamMembershipRow(team_id=team_id, user_id=self.actor, active=True))
                session.add(ProjectRow(name="fixture", owner_team_id=team_id))
            session.add(TeamMembershipRow(team_id=self.team, user_id=self.actor, active=True))
            session.add(ProjectRow(id=self.target, name="selected", owner_team_id=self.team))

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def exact(self, project: UUID | None = None) -> CurrentRauthyPlatformMembership | None:
        return await self.projection.resolve_project(
            issuer=_ISSUER, subject=_SUBJECT, project_uuid=project or self.target
        )

    async def test_exact_sql_succeeds_beyond_inventory_limit_and_is_scoped(self) -> None:
        inventory = await self.projection.resolve(issuer=_ISSUER, subject=_SUBJECT)
        assert inventory is not None
        self.assertTrue(inventory.directory_paged)
        self.assertEqual(inventory.projects, ())
        self.db.statements.clear()
        current = await self.exact()
        assert current is not None
        self.assertEqual(len(current.projects), 1)
        self.assertEqual(current.projects[0].project_id, self.target)
        self.assertEqual(
            current.projects[0].permissions, ("use_resources", "approve_agent_session")
        )
        self.assertTrue(current.teams[0].owner)
        self.assertTrue(current.teams[0].member)
        self.assertEqual(len(self.db.statements), 1)
        compiled = self.db.statements[0].compile(dialect=self.db.engine.dialect)
        parameters = compiled.params
        assert parameters is not None
        self.assertIn(self.target, parameters.values())
        self.assertIn("projects.projects.id =", str(compiled))
        self.assertIn("memberships.active IS true", str(compiled))
        self.assertNotIn("LIMIT", str(compiled))

    async def test_current_team_loss_deletion_foreign_and_personal_scope(self) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                update(TeamRow).where(TeamRow.id == self.team).values(owner_user_id=uuid4())
            )
        current = await self.exact()
        assert current is not None
        self.assertEqual(current.projects[0].permissions, ("use_resources",))
        async with self.db.transaction() as session:
            await session.execute(
                update(TeamMembershipRow)
                .where(TeamMembershipRow.team_id == self.team)
                .values(active=False)
            )
        self.assertIsNone(await self.exact())
        self.assertIsNone(await self.exact(uuid4()))
        personal = uuid4()
        async with self.db.transaction() as session:
            session.add(ProjectRow(id=personal, name="personal", owner_user_id=self.actor))
        result = await self.exact(personal)
        assert result is not None
        self.assertEqual(result.teams, ())
        self.assertEqual(result.projects[0].owner_id, self.actor)
        async with self.db.transaction() as session:
            await session.execute(
                update(ProjectRow)
                .where(ProjectRow.id == personal)
                .values(lifecycle_status="deleted")
            )
        self.assertIsNone(await self.exact(personal))

    async def test_disabled_link_and_expiry_at_transaction_exit_deny(self) -> None:
        self.links.current = replace(self.links.current, enabled=False)
        self.assertIsNone(await self.exact())
        self.assertFalse(self.db.statements)
        self.links.current = replace(
            self.links.current,
            enabled=True,
            expires_at=datetime.now(UTC) + timedelta(milliseconds=25),
        )
        self.db.exit_delay = 0.04
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            await self.exact()

    async def test_two_owner_bff_scoped_me_and_sessions_do_not_enumerate(self) -> None:
        app = FastAPI()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://briareus-platform:8000"
        ) as private:
            peer = PanelPeerFixture(private)
            app.include_router(
                current_platform_context_router(projection=self.projection, attestor=peer)
            )
            source = PrivatePlatformCurrentClient(peer=peer)
            public_app = FastAPI()

            async def list_sessions(
                *,
                actor: UUID,
                project: UUID,
                limit: int,
            ) -> tuple[CurrentSessionSnapshot, ...]:
                assert actor == self.actor and project == self.target and 1 <= limit <= 50
                return ()

            browser_sessions = Mock(spec=OidcBrowserSessionStore)
            browser_sessions.get_session = AsyncMock(side_effect=BrowserFixture().get_session)
            approvals = Mock(spec=ApprovalManagementPort)
            approvals.list_sessions = AsyncMock(side_effect=list_sessions)
            public_app.include_router(
                platform_membership_router(
                    browser_sessions, source=source, approval_source=approvals
                )
            )
            async with AsyncClient(
                transport=ASGITransport(app=public_app),
                base_url=_ORIGIN,
                cookies={"__Host-briareus_oidc_session": _COOKIE},
            ) as public:
                ordinary = await public.get("/api/v1/auth/me")
                self.assertEqual(ordinary.status_code, 200)
                self.assertTrue(ordinary.json()["directory_paged"])
                self.assertEqual(ordinary.json()["projects"], [])
                scoped = await public.get(
                    "/api/v1/auth/me", params={"project_uuid": str(self.target)}
                )
                self.assertEqual(scoped.status_code, 200, scoped.text)
                self.assertEqual(scoped.json()["projects"][0]["id"], str(self.target))
                self.assertEqual(len(scoped.json()["teams"]), 1)
                sessions = await public.get(
                    "/api/v1/agent-sessions", params={"project_uuid": str(self.target)}
                )
                self.assertEqual(sessions.status_code, 200, sessions.text)
                peer.bad_scope = True
                mismatch = await public.get(
                    "/api/v1/auth/me", params={"project_uuid": str(self.target)}
                )
                self.assertEqual(mismatch.status_code, 503)
                peer.bad_scope = False
                denied = await public.get("/api/v1/auth/me", params={"project_uuid": str(uuid4())})
                self.assertEqual(denied.status_code, 403)
                ambiguous = await public.get(
                    "/api/v1/auth/me",
                    params=[("project_uuid", str(self.target)), ("project_uuid", str(uuid4()))],
                )
                self.assertEqual(ambiguous.status_code, 422)
                self.assertEqual(scoped.headers["cache-control"], "no-store")

    async def test_private_access_route_requires_exact_project_attestation(self) -> None:
        class AccessPeerFixture:
            async def verify(
                peer_self, request: Request, query: AccessMembershipQuery
            ) -> VerifiedAccessProjectPeer:
                assert request.method == "POST" and query.issuer == _ISSUER
                assert query.subject == _SUBJECT
                return VerifiedAccessProjectPeer(
                    "briareus:platform", "authorization", _ISSUER, _SUBJECT, self.target, deadline()
                )

        app = FastAPI()
        app.include_router(
            oidc_access_project_router(projection=self.projection, attestor=AccessPeerFixture())
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://briareus-platform:8000"
        ) as client:
            query = {"issuer": _ISSUER, "subject": _SUBJECT, "project_uuid": str(self.target)}
            response = await client.post(
                "/internal/v1/platform/oidc/project-member",
                json=query,
                headers={"Authorization": "Bearer fixture-peer"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["actor_uuid"], str(self.actor))
            self.assertNotIn("teams", response.json())
            query["project_uuid"] = str(uuid4())
            denied = await client.post(
                "/internal/v1/platform/oidc/project-member",
                json=query,
                headers={"Authorization": "Bearer fixture-peer"},
            )
            self.assertEqual(denied.status_code, 403)


class MigrationHistory(NamedTuple):
    owner: Literal["access", "platform", "resources"]
    directory: str
    files: tuple[str, ...]
    versions: tuple[str, ...]


class GreenfieldOwnerBaselineTests(unittest.TestCase):
    """Canonical histories and packaged copies retain reviewed source and fail closed."""

    root = Path(__file__).resolve().parents[3]
    histories: tuple[MigrationHistory, ...] = (
        MigrationHistory(
            "access",
            "authorization",
            ("0001_access_baseline.py",),
            ("access_20261015_0001",),
        ),
        MigrationHistory(
            "platform",
            "platform",
            ("0001_platform_baseline.py",),
            ("platform_20261018_0001",),
        ),
        MigrationHistory(
            "resources",
            "resources",
            (
                "0001_resources_baseline.py",
                "0002_nodes.py",
                "0003_runtime_policy.py",
                "0004_node_execution_journal.py",
                "0005_typed_node_records.py",
            ),
            (
                "resources_20261018_0001",
                "resources_20261019_0002",
                "resources_20261020_0003",
                "resources_20261021_0004",
                "resources_20261023_0005",
            ),
        ),
    )

    def test_platform_current_sql_has_exactly_one_new_epoch_revision(self) -> None:
        history = list(ScriptDirectory.from_config(owner_config("platform")).walk_revisions())
        self.assertEqual(len(history), 1)
        module = history[0].module
        self.assertEqual(module.revision, "platform_20261018_0001")
        self.assertIsNone(module.down_revision)
        current = _ddl_source("platform")
        self.assertEqual(module._DDL, current)
        self.assertEqual(
            module.source_signature,
            hashlib.sha256("\n--DDL--\n".join(current).encode()).hexdigest(),
        )
        self.assertEqual(len(current), 26)
        self.assertEqual(
            sum(sql.startswith("CREATE TABLE control.rauthy_user_links") for sql in current),
            1,
        )
        self.assertFalse(
            any(sql.startswith(("DROP", "DELETE", "TRUNCATE", "ALTER")) for sql in current)
        )

    def test_backend_canonical_histories_are_reviewed_and_packaged(self) -> None:
        for case in self.histories:
            with self.subTest(owner=case.owner):
                local = self.root / "services" / case.directory / "migrations"
                with patch(
                    "common.owner_migrations.__file__",
                    str(self.root / "services/common/owner_migrations.py"),
                ):
                    self.assertEqual(_migration_directory(case.owner), local)
                files = {p.name: p for p in (local / "versions").glob("*.py")}
                self.assertEqual(set(files), set(case.files))
                config = Config()
                config.set_main_option("script_location", str(local))
                graph = ScriptDirectory.from_config(config)
                history = list(graph.walk_revisions())
                self.assertEqual(graph.get_heads(), [case.versions[-1]])
                self.assertEqual(tuple(item.revision for item in reversed(history)), case.versions)
                self.assertIsNone(history[-1].down_revision)
                for newer, older in pairwise(history):
                    self.assertEqual(newer.down_revision, older.revision)
                dockerfile = (local.parent / "Dockerfile").read_text()
                self.assertIn(f"COPY services/{case.directory}/migrations/env.py", dockerfile)
                self.assertNotIn("COPY scripts/alembic_owners/", dockerfile)
                for revision in history:
                    source_file = revision.module.__file__
                    assert source_file is not None
                    source = Path(source_file)
                    self.assertEqual(
                        hashlib.sha256(source.read_bytes()).hexdigest(),
                        _NEW_EPOCH_SOURCE_HASHES[revision.revision],
                    )
                    self.assertIn(
                        f"COPY services/{case.directory}/migrations/versions/{source.name}",
                        dockerfile,
                    )
                    self.assertIn(f"/common/alembic_owners/{case.owner}/", dockerfile)
                baseline = TypeAdapter(tuple[str, ...]).validate_python(history[-1].module._DDL)
                self.assertTrue(baseline)
                self.assertTrue(
                    all(
                        sql.startswith(
                            (
                                "CREATE TABLE",
                                "CREATE INDEX",
                                "CREATE UNIQUE INDEX",
                                "CREATE SCHEMA",
                            )
                        )
                        for sql in baseline
                    )
                )

    def test_only_reviewed_epoch_or_completely_empty_database_is_eligible(self) -> None:
        for case in self.histories:
            with self.subTest(owner=case.owner):
                _require_owner_revision_epoch(
                    case.owner,
                    None,
                    contains_objects=False,
                    present_schemas={"public"},
                )
                for version in case.versions:
                    _require_owner_revision_epoch(
                        case.owner,
                        version,
                        contains_objects=True,
                        present_schemas={"public"},
                    )
                previous = (
                    "access_0001",
                    "platform_0001",
                    "platform_0002",
                    "platform_0003",
                    "platform_0004",
                    "platform_20261015_0001",
                    "resources_0001",
                    "resources_0002",
                    "resources_20261015_0001",
                    "unknown",
                )
                for version in previous:
                    with self.subTest(previous=version), self.assertRaises(OwnerSchemaRejected):
                        _require_owner_revision_epoch(
                            case.owner,
                            version,
                            contains_objects=True,
                            present_schemas={"public"},
                        )
                for objects, schemas in (
                    (True, {"public"}),
                    (False, {"public", "control"}),
                    (False, {"public", "resources"}),
                ):
                    with self.assertRaises(OwnerSchemaRejected):
                        _require_owner_revision_epoch(
                            case.owner,
                            None,
                            contains_objects=objects,
                            present_schemas=schemas,
                        )

    def test_greenfield_platform_runs_exact_orm_ddl_in_sequence(self) -> None:
        module = next(ScriptDirectory.from_config(owner_config("platform")).walk_revisions()).module
        executed: list[str] = []

        class RecordingBind:
            def exec_driver_sql(self, statement: str) -> None:
                executed.append(statement)

        with patch.object(module.op, "get_bind", return_value=RecordingBind()):
            module.upgrade()
        self.assertEqual(executed, list(_ddl_source("platform")))
        with self.assertRaisesRegex(RuntimeError, "recreated explicitly"):
            module.downgrade()

    def test_old_epoch_is_rejected_before_alembic_upgrade(self) -> None:
        def deny_old(_conn: Connection, _settings: OwnerDatabaseSettings) -> None:
            _require_owner_revision_epoch(
                "platform",
                "platform_0003",
                contains_objects=True,
                present_schemas={"public"},
            )

        settings = Mock(spec=OwnerDatabaseSettings)
        settings.owner = "platform"
        with (
            patch("common.owner_migrations._identity", side_effect=deny_old),
            patch("common.owner_migrations.command.upgrade") as actual_upgrade,
            self.assertRaises(OwnerSchemaRejected),
        ):
            _upgrade_owner(Mock(spec=Connection), Config(), settings)
        actual_upgrade.assert_not_called()

    def test_changed_reviewed_source_is_rejected(self) -> None:
        with (
            patch.dict(_NEW_EPOCH_SOURCE_HASHES, {"platform_20261018_0001": "0" * 64}),
            self.assertRaisesRegex(OwnerSchemaRejected, "greenfield Alembic source changed"),
        ):
            owner_config("platform")
