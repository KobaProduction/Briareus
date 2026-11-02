"""Explicit disposable PostgreSQL test source with per-test isolated schemas."""

import asyncio
import os
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from uuid import uuid4

from projects._rauthy_user_links import RauthyUserLinkRow
from sqlalchemy import Table, event, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ClauseElement

from agents._persistence import AgentIdentityRow
from common.platform_db import PlatformDatabase
from projects._control_ledger import OwnerAuditRow, OwnerOutboxRow
from projects._persistence import ProjectRow
from teams._persistence import TeamMembershipRow, TeamRow


class PostgresOwnerFixture(PlatformDatabase):
    def __init__(self) -> None:
        target = os.environ.get("BRIAREUS_PLATFORM_TEST_DATABASE_URL")
        if target is None:
            raise RuntimeError(
                "BRIAREUS_PLATFORM_TEST_DATABASE_URL must identify disposable PostgreSQL"
            )
        url = make_url(target)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in {"localhost", "127.0.0.1", "::1"}
            or not re.fullmatch(r"briareus_platform_test(?:_[a-z0-9]+)?", url.database or "")
        ):
            raise ValueError(
                "Platform tests require loopback PostgreSQL and a dedicated test database"
            )
        prefix = "platform_test_" + uuid4().hex
        self._schemas = {
            kind: prefix + "_" + kind for kind in ("teams", "projects", "control", "agents")
        }
        self._sql = create_async_engine(
            url, execution_options={"schema_translate_map": self._schemas}
        )
        self._sessions = async_sessionmaker(self._sql, expire_on_commit=False)
        # Production selectors pin a logical owner name; SQL still goes only to
        # the separately qualified disposable URL and isolated test schemas.
        self.engine = create_async_engine(url.set(database="briareus_platform"))
        self.sessions = self._sessions
        self.statements: list[ClauseElement] = []
        self.exit_delay = 0.0

    async def initialize(self) -> None:
        async with self._sql.begin() as connection:
            for schema in self._schemas.values():
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for table in (
                TeamRow.__table__,
                TeamMembershipRow.__table__,
                ProjectRow.__table__,
                RauthyUserLinkRow.__table__,
                AgentIdentityRow.__table__,
                OwnerAuditRow.__table__,
                OwnerOutboxRow.__table__,
            ):
                if not isinstance(table, Table):
                    raise AssertionError("Owner fixture requires a concrete ORM Table")
                await connection.run_sync(table.create)
        event.listen(self._sql.sync_engine, "before_execute", self._record)

    def _record(
        self,
        _connection: Connection,
        statement: ClauseElement,
        _multiparams: Sequence[Mapping[str, object]],
        _params: Mapping[str, object],
        _execution_options: Mapping[str, object],
    ) -> None:
        if isinstance(statement, Select):
            self.statements.append(statement)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session, session.begin():
            yield session
        if self.exit_delay:
            await asyncio.sleep(self.exit_delay)

    async def close(self) -> None:
        async with self._sql.begin() as connection:
            for schema in reversed(tuple(self._schemas.values())):
                if not re.fullmatch(
                    r"platform_test_[0-9a-f]{32}_(teams|projects|control|agents)", schema
                ):
                    raise ValueError("Refusing cleanup outside the fixture's own schemas")
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await self._sql.dispose()
        await self.engine.dispose()
