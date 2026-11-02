"""PostgreSQL validation and connection mechanics without owner storage bindings."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import ClassVar, Self

from pydantic import SecretStr, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from owner_protocol.domain.authority import OwnerName

_LOCK_TIMEOUT_MS = 3000
_STATEMENT_TIMEOUT_MS = 30000
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z", re.ASCII)
_HOST = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?\Z", re.ASCII)


class DatabaseSettingsMechanics:
    """Validators inherited by each local settings model's declared fields."""

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr

    @field_validator("postgres_host")
    @classmethod
    def _host(cls, value: str) -> str:
        if not _HOST.fullmatch(value) or len(value) > 253:
            raise ValueError("POSTGRES_HOST must be an internal DNS host")
        return value

    @field_validator("postgres_db", "postgres_user")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("PostgreSQL database/user must be canonical identifiers")
        return value

    @field_validator("postgres_password")
    @classmethod
    def _password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or raw.isspace() or raw.startswith(("{{", "${")) or len(raw) > 8192:
            raise ValueError("POSTGRES_PASSWORD must resolve to a nonempty secret")
        return value

    @property
    def url(self) -> URL:
        """SQLAlchemy quotes credentials safely; no second DATABASE_URL input."""
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


def require_owner_database(actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError("POSTGRES_DB does not match this durable owner's logical database")


def connect_database(url: URL) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, sessions


@asynccontextmanager
async def database_transaction(
    sessions: async_sessionmaker[AsyncSession],
    conflict_error: type[Exception],
    timeout_error: type[Exception],
) -> AsyncIterator[AsyncSession]:
    """Bounded one-command transaction, errors preserve retry semantics."""
    try:
        async with sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config('lock_timeout', :value, true)"),
                {"value": f"{_LOCK_TIMEOUT_MS}ms"},
            )
            await session.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": f"{_STATEMENT_TIMEOUT_MS}ms"},
            )
            yield session
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate in {"55P03", "40P01", "40001"}:
            raise conflict_error(
                "transaction concurrency conflict; retry with the same key"
            ) from None
        if sqlstate == "57014":
            raise timeout_error("database operation deadline exceeded") from None
        raise


async def close_database(engine: AsyncEngine) -> None:
    await engine.dispose()


class OwnerDatabaseValidation:
    """The local model supplies its own database-name lookup."""

    postgres_db: str
    owner: OwnerName
    _owner_database_lookup: ClassVar[Callable[[OwnerName], str]]

    @model_validator(mode="after")
    def _owner_database(self) -> Self:
        require_owner_database(self.postgres_db, type(self)._owner_database_lookup(self.owner))
        return self


class DatabaseRuntime[SettingsT: DatabaseSettingsMechanics]:
    """Each local database instance creates and owns its engine and sessions."""

    _conflict_error: ClassVar[type[Exception]]
    _timeout_error: ClassVar[type[Exception]]

    def __init__(self, settings: SettingsT) -> None:
        self.engine: AsyncEngine
        self.sessions: async_sessionmaker[AsyncSession]
        self.engine, self.sessions = connect_database(settings.url)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Bounded one-command transaction, errors preserve retry semantics."""
        async with database_transaction(
            self.sessions, type(self)._conflict_error, type(self)._timeout_error
        ) as session:
            yield session

    async def close(self) -> None:
        await close_database(self.engine)


class _PostgresConnection:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> None:
        url = URL.create(
            "postgresql+asyncpg",
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    async def ensure_schema(self) -> bool:
        """Retired. Only independently reviewed owner Alembic may create DDL."""
        raise RuntimeError("legacy schema initializer disabled; use reviewed owner migrations")

    async def dispose(self) -> None:
        await self.engine.dispose()


class _PrivateDatabaseBinding[DatabaseT]:
    def __init__(self, database: DatabaseT) -> None:
        self._database = database


class _DatabaseBinding[DatabaseT]:
    def __init__(self, database: DatabaseT) -> None:
        self.database = database


class _DatabaseCipherBinding[DatabaseT, CipherT]:
    def __init__(self, database: DatabaseT, cipher: CipherT) -> None:
        self._database, self._cipher = database, cipher


class _SessionBinding[SessionT]:
    def __init__(self, session: SessionT) -> None:
        self._session = session


class _SessionCipherBinding[SessionT, CipherT]:
    def __init__(self, session: SessionT, cipher: CipherT) -> None:
        self._session = session
        self._cipher = cipher
