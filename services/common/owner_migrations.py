"""Owner-only Alembic graph and fail-closed PostgreSQL startup coordinator.

No DDL occurs on import. Owners never inspect or migrate another owner's DB.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from alembic import command, context
from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import CreateIndex, CreateTable

from common.application.schema_verification import VerifyOwnerSchema
from common.domain.schema_contracts import OwnerSchemaRejected as OwnerSchemaRejected
from common.infrastructure.schema_inspection import SqlOwnerSchemaInspection
from common.owner_registry import owner_metadata
from common.owner_startup_diagnostics import Phase, is_permanent_connection_failure, safe_sqlstate
from common.platform_db import OWNER_DB_NAMES, OwnerDatabaseSettings, OwnerName, PlatformDatabase


class OwnerDatabaseConnectionUnavailable(OwnerSchemaRejected):
    """Sanitized startup connectivity failure; never retains raw DB exception."""

    def __init__(self, sqlstate: str | None) -> None:
        self.sqlstate = sqlstate
        super().__init__("owner database connection unavailable")


@dataclass(frozen=True, slots=True)
class OwnerSchemaStatus:
    owner: OwnerName
    revision: str
    changed: bool
    tables: int


@dataclass(frozen=True, slots=True)
class OwnerMigrationLock:
    namespace: int
    resource: int


def _ddl_source(owner: OwnerName) -> tuple[str, ...]:
    metadata = owner_metadata(owner)
    result = [
        f'CREATE SCHEMA "{schema}"'
        for schema in sorted({t.schema for t in metadata.tables.values() if t.schema is not None})
    ]
    pg = dialect()  # type: ignore[no-untyped-call]
    for table in metadata.sorted_tables:
        result.append(str(CreateTable(table).compile(dialect=pg)).strip())
        result.extend(
            str(CreateIndex(index).compile(dialect=pg)).strip()
            for index in sorted(table.indexes, key=lambda ix: ix.name or "")
        )
    return tuple(result)


# New explicit *greenfield epoch* of current Backend owner schemas.
# Operator-approved experimental service data reset is separate from this
# source change. Old historical versions are intentionally NOT accepted as
# the new revision even when they happen to contain similar tables.
# Rauthy/provider auth DB and filesystem roots are NOT owner reset targets.
_GREENFIELD_OWNER_EPOCH: frozenset[OwnerName] = frozenset({"access", "platform", "resources"})
_APPROVED_BASELINE_HASHES: dict[OwnerName, str] = {
    "identity": "ee13ba6b4266a325be4f5860e3a321c43662e2409bfcd88f69ccf9969f8466eb",
    "access": "b9db1f587cb5412d7d08616acac58468d910c9a535bc9b7de77a5570a1652b2c",
    "platform": "d73c73e7a0a1ccf5fd175b10fe10d5f13751dd325a7d04671f8629988b8d644e",
    "resources": "8d90e38d55364e7c9d5622ff2063ff82687e73ab72015313933a912293a9d1c3",
    "files": "395244365a0bd125869329b31554e285d8313f3f8253bd6596006c73421a1679",
    "runtime": "acc05a7994ad166610ad02b4c189f7c776df53a4a922bd75fa12ed64d7b46b75",
    "reverse": "7876512ca2e5b8a47ba7f1dccd13ede9a58378fea4133de400e8e9ff884fe517",
    "ingest": "88c8db8381bfdf26e72f1aa33bd6915a48ef22b2e48164b14ce77c",
}
# Do not change other owner migration histories without their owner.
_APPROVED_INTERMEDIATE_SIGNATURES: dict[str, str] = {
    "resources_20261021_0004": "334fac98bf91a945c34d4cebab017d8c999453f37025a20ffa8a881ed2150d09",
    "resources_20261020_0003": "f4cfcd457b042ff2dc67607e64684cc2fc436a2b4f927350c448916a5eebd49e",
    "resources_20261019_0002": "1b893953f5189e131ec696290993274347718aa594db13853ca8a1c89d647662",
    "runtime_0002": "27d61748555c275ca1a09c29b5faba52343cdb85624b9825778661372b7c9136",
}
# The selected Backend greenfield revision content is pinned AS A WHOLE, not
# just by its ORM DDL signature; this prevents a different imperative upgrade
# with the same nominal head/version from becoming a silent privilege change.
_NEW_EPOCH_SOURCE_HASHES: dict[str, str] = {
    "resources_20261023_0005": "c83f49174fd6299367957d9dfca81236130810642bd3a8e261285616146af06a",
    "resources_20261021_0004": "8508fb17ae7dc9c96e6ce8cb648b72bb261d615cecb48160d9eee6acc399dd88",
    "resources_20261020_0003": "56c8fb5ea02fbba933eeea8ec5271e5adf7d763371955ecc0e0844cf3c4eddf7",
    "access_20261015_0001": "0a576fe65298b14581e683475166f68c36e6f51be87936b55540d4136e61d7fd",
    "platform_20261018_0001": "3c1dd8a7ba55f6086e80cc12040d4570ec91f3116e81dccb58d2be38a048c8e3",
    "resources_20261018_0001": "911a0418f8f3f56c1982ff92ac330077aa683385a85f032c7cbc4a7c89a606d1",
    "resources_20261019_0002": "7aa0a8a5bbed9f45020c74a30415252686817448d551d2866e7f1a3409694fec",
}
_REVIEWED_VERSIONS: dict[OwnerName, tuple[str, ...]] = {
    "identity": ("identity_0001", "identity_0002"),
    "access": ("access_20261015_0001",),
    "platform": ("platform_20261018_0001",),
    "resources": (
        "resources_20261018_0001",
        "resources_20261019_0002",
        "resources_20261020_0003",
        "resources_20261021_0004",
        "resources_20261023_0005",
    ),
    "files": ("files_0001", "files_0002"),
    "runtime": ("runtime_0001", "runtime_0002", "runtime_0003"),
    "reverse": ("reverse_0001", "reverse_0002"),
    "ingest": ("ingest_0001",),
}


def _head(owner: OwnerName) -> str:
    return _REVIEWED_VERSIONS[owner][-1]


def _accepted_versions(owner: OwnerName) -> frozenset[str]:
    return frozenset(_REVIEWED_VERSIONS[owner])


def _migration_directory(owner: OwnerName) -> Path:
    package = Path(__file__).resolve().parent / "alembic_owners" / owner
    source = Path(__file__).resolve().parents[2] / "scripts" / "alembic_owners" / owner
    # Flat owner-local source is canonical for the three Backend greenfield
    # databases. Installed source-only owner wheels retain the copied
    # /app/src/common/alembic_owners/<owner>/ history as first priority.
    local_owner = {
        "access": Path(__file__).resolve().parents[2] / "services/authorization/migrations",
        "platform": Path(__file__).resolve().parents[2] / "services/platform/migrations",
        "resources": Path(__file__).resolve().parents[2] / "services/resources/migrations",
    }.get(owner)
    directory = (
        package
        if (package / "env.py").is_file()
        else local_owner
        if local_owner is not None and (local_owner / "env.py").is_file()
        else source
    )
    if not (directory / "env.py").is_file():
        raise OwnerSchemaRejected("owner migration history missing from installed image")
    return directory


def _require_reviewed_sources(owner: OwnerName, revisions: list[Script]) -> None:
    if owner in _GREENFIELD_OWNER_EPOCH:
        # A fresh baseline must have exactly the reviewed imperative source,
        # not just the same ORM/DDL hash or a reused historical Alembic ID.
        for revision in revisions:
            expected_source = _NEW_EPOCH_SOURCE_HASHES.get(revision.revision)
            source_path = getattr(revision.module, "__file__", None)
            if (
                expected_source is None
                or not isinstance(source_path, str)
                or not source_path.endswith(".py")
                or hashlib.sha256(Path(source_path).read_bytes()).hexdigest() != expected_source
            ):
                raise OwnerSchemaRejected("reviewed greenfield Alembic source changed")


def _require_reviewed_graph(owner: OwnerName, revisions: list[Script]) -> None:
    if not revisions or revisions[-1].revision != _REVIEWED_VERSIONS[owner][0]:
        raise OwnerSchemaRejected("owner migration baseline missing from reviewed graph")
    if revisions[-1].down_revision is not None:
        raise OwnerSchemaRejected("owner migration graph has a foreign ancestor")
    if any(newer.down_revision != older.revision for newer, older in pairwise(revisions)):
        raise OwnerSchemaRejected("branched/merged owner schema history is forbidden")
    if frozenset(revision.revision for revision in revisions) != _accepted_versions(owner):
        raise OwnerSchemaRejected("unknown intermediate owner schema revision")
    if getattr(revisions[-1].module, "source_signature", None) != _APPROVED_BASELINE_HASHES[owner]:
        raise OwnerSchemaRejected("frozen owner 0001 baseline was modified")
    for old in revisions[1:-1]:
        pinned = _APPROVED_INTERMEDIATE_SIGNATURES.get(old.revision)
        if pinned is None or getattr(old.module, "source_signature", None) != pinned:
            raise OwnerSchemaRejected("pre-A13 owner migration history was altered")


def owner_config(owner: OwnerName) -> Config:
    directory = _migration_directory(owner)
    cfg = Config()
    cfg.set_main_option("script_location", str(directory))
    graph = ScriptDirectory.from_config(cfg)
    expected = _head(owner)
    if graph.get_heads() != [expected]:
        raise OwnerSchemaRejected("unexpected owner Alembic heads or branching")
    revisions = list(graph.walk_revisions(head=expected))
    _require_reviewed_sources(owner, revisions)
    _require_reviewed_graph(owner, revisions)
    sha = hashlib.sha256("\n--DDL--\n".join(_ddl_source(owner)).encode()).hexdigest()
    if getattr(revisions[0].module, "source_signature", None) != sha:
        raise OwnerSchemaRejected("current ORM source differs from reviewed owner head")
    return cfg


def run_owner_alembic_env(owner: OwnerName) -> None:
    connection: Connection | None = context.config.attributes.get("connection")
    if connection is None or context.is_offline_mode():
        raise OwnerSchemaRejected("only locked owner startup may migrate; no standalone SQL")
    context.configure(
        connection=connection,
        target_metadata=owner_metadata(owner),
        version_table="alembic_version",
        version_table_schema="public",
        include_schemas=True,
        transactional_ddl=True,
        transaction_per_migration=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def _revision(conn: Connection) -> str | None:
    if conn.scalar(text("SELECT to_regclass('public.alembic_version')")) is None:
        return None
    rows = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    if len(rows) != 1:
        raise OwnerSchemaRejected("invalid owner revision-table cardinality")
    return str(rows[0])


def _require_owner_revision_epoch(
    owner: OwnerName,
    revision: str | None,
    *,
    contains_objects: bool,
    present_schemas: set[str],
) -> None:
    """Only truly empty owner databases can enter the new baseline epoch.

    The externally preserved briareus_rauthy provider DB is NOT in this
    owner's namespace and cannot be reset or stamped by this function.
    Old Alembic revisions, even with an identical current ORM DDL shape,
    are deliberately incompatible with the new greenfield owner epoch.
    """
    if revision is None:
        if contains_objects:
            raise OwnerSchemaRejected("nonempty unversioned owner database")
        if owner in _GREENFIELD_OWNER_EPOCH and present_schemas - {"public"}:
            raise OwnerSchemaRejected("new owner baseline requires empty logical database")
    elif revision not in _accepted_versions(owner):
        raise OwnerSchemaRejected("unknown or previous-epoch owner migration version")


def _identity(conn: Connection, settings: OwnerDatabaseSettings) -> None:
    actual_db, actual_user = conn.execute(text("SELECT current_database(), current_user")).one()
    if (
        actual_db != OWNER_DB_NAMES[settings.owner]
        or actual_db != settings.postgres_db
        or actual_user != settings.postgres_user
    ):
        raise OwnerSchemaRejected("owner PostgreSQL database or principal mismatch")
    allowed = {t.schema for t in owner_metadata(settings.owner).tables.values()} | {"public"}
    present = set(
        conn.execute(
            text(
                """SELECT schema_name FROM information_schema.schemata
                WHERE schema_name !~ '^pg_' AND schema_name <> 'information_schema'"""
            )
        ).scalars()
    )
    if present - allowed:
        raise OwnerSchemaRejected("foreign namespace in owner database")
    owned_sequences = {
        f"{table.schema}.{table.name}_{column.name}_seq"
        for table in owner_metadata(settings.owner).tables.values()
        for column in table.columns
        if column.primary_key
        and column.autoincrement is not False
        and column.type.__class__.__name__ in {"Integer", "BigInteger", "SmallInteger"}
    }
    unexpected = conn.execute(
        text(
            """SELECT n.nspname, c.relname, c.relkind::text AS relkind FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                AND c.relkind IN ('r','p','v','m','f','S')"""
        )
    ).all()
    if any(
        f"{schema}.{name}"
        not in (
            set(owner_metadata(settings.owner).tables)
            | {"public.alembic_version"}
            | owned_sequences
        )
        or (kind == "S" and f"{schema}.{name}" not in owned_sequences)
        or kind not in {"r", "p", "S"}
        for schema, name, kind in unexpected
    ):
        raise OwnerSchemaRejected("unexpected legacy or cross-owner database object")
    _require_owner_revision_epoch(
        settings.owner,
        _revision(conn),
        contains_objects=bool(unexpected),
        present_schemas=present,
    )


def _verify(conn: Connection, settings: OwnerDatabaseSettings) -> int:
    source = SqlOwnerSchemaInspection(
        owner_metadata(settings.owner), inspect(conn), lambda: _revision(conn)
    )
    return VerifyOwnerSchema(source, _head(settings.owner)).execute().tables


def _upgrade_owner(
    conn: Connection,
    cfg: Config,
    settings: OwnerDatabaseSettings,
) -> bool:
    # Inspired by vpn-core's MigrationManager: applying reviewed Alembic
    # revisions is one operation; schema inspection is a separate read-only
    # operation AFTER the migration's transaction has committed.
    _identity(conn, settings)
    changed = _revision(conn) != _head(settings.owner)
    if changed:
        cfg.attributes["connection"] = conn
        try:
            command.upgrade(cfg, "head")
        finally:
            cfg.attributes.pop("connection", None)
    return changed


async def _connect_owner(db: PlatformDatabase) -> AsyncConnection:
    conn: AsyncConnection | None = None
    deadline = time.monotonic() + 35
    last_connect_sqlstate: str | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncio.wait_for(db.engine.connect(), timeout=5)
            break
        except (OSError, DBAPIError, TimeoutError) as error:
            # Missing logical DB, invalid role/password and denied schema
            # are NOT transient. Never hide the original SQLSTATE behind
            # another 35 seconds of identical attempts or log DBAPI args.
            last_connect_sqlstate = safe_sqlstate(error)
            if is_permanent_connection_failure(error):
                raise OwnerDatabaseConnectionUnavailable(last_connect_sqlstate) from None
            await asyncio.sleep(1)
    if conn is None:
        raise OwnerDatabaseConnectionUnavailable(last_connect_sqlstate) from None
    return conn


async def migrate_owner(
    db: PlatformDatabase,
    settings: OwnerDatabaseSettings,
    *,
    phase_change: Callable[[Phase], None] | None = None,
) -> OwnerSchemaStatus:
    """One owner, locked DDL, no DBA fallback; optional safe diagnostic stage."""
    cfg = owner_config(settings.owner)
    conn = None
    held = False
    lock = OwnerMigrationLock(140995, 49001 + list(OWNER_DB_NAMES).index(settings.owner))
    try:
        if phase_change is not None:
            phase_change("connect")
        conn = await _connect_owner(db)
        if phase_change is not None:
            phase_change("migration_lock")
        async with asyncio.timeout(210):
            deadline = time.monotonic() + 70
            while time.monotonic() < deadline:
                held = bool(
                    await conn.scalar(
                        text("SELECT pg_try_advisory_lock(:namespace, :resource)"),
                        {"namespace": lock.namespace, "resource": lock.resource},
                    )
                )
                await conn.commit()
                if held:
                    break
                await asyncio.sleep(1)
            if not held:
                raise OwnerSchemaRejected("owner startup migration lock timeout")
            if phase_change is not None:
                phase_change("alembic_upgrade")
            async with conn.begin():
                await conn.execute(text("SELECT set_config('statement_timeout', '90000ms', true)"))
                await conn.execute(text("SELECT set_config('lock_timeout', '75000ms', true)"))
                changed = await conn.run_sync(_upgrade_owner, cfg, settings)
            # vpn-core separates upgrade from assert-current: strict schema
            # comparison must not roll back a committed Alembic revision.
            # Keep the same owner advisory lock across both phases.
            if phase_change is not None:
                phase_change("owner_schema_verify")
            async with conn.begin():
                observed = await conn.run_sync(_read_owner, settings)
            return OwnerSchemaStatus(
                settings.owner,
                observed.revision,
                changed,
                observed.tables,
            )
    except TimeoutError:
        raise OwnerSchemaRejected("owner startup deadline exceeded") from None
    finally:
        if conn is not None:
            await _close_migration_connection(conn, held, lock)


async def _close_migration_connection(
    conn: AsyncConnection, held: bool, lock: OwnerMigrationLock
) -> None:
    if held:
        try:
            await conn.rollback()
            released = await conn.scalar(
                text("SELECT pg_advisory_unlock(:namespace, :resource)"),
                {"namespace": lock.namespace, "resource": lock.resource},
            )
            await conn.commit()
            if not released:
                await conn.invalidate()
        except Exception:
            await conn.invalidate()
    await conn.close()


async def verify_owner(db: PlatformDatabase, settings: OwnerDatabaseSettings) -> OwnerSchemaStatus:
    """Strict read-only owner readiness, never calls Alembic or runs DDL."""
    owner_config(settings.owner)
    try:
        async with db.engine.connect() as conn, conn.begin():
            return await conn.run_sync(_read_owner, settings)
    except OwnerSchemaRejected:
        raise
    except (DBAPIError, OSError, TimeoutError) as error:
        # Even after a successful migration, an expired/revoked owner role
        # or unavailable DB must preserve its SAFE SQLSTATE for P0 incident
        # triage rather than being reported as a mystery schema mismatch.
        raise OwnerDatabaseConnectionUnavailable(safe_sqlstate(error)) from None
    except Exception:
        raise OwnerSchemaRejected("owner read-only schema verification unavailable") from None


def _read_owner(conn: Connection, settings: OwnerDatabaseSettings) -> OwnerSchemaStatus:
    _identity(conn, settings)
    return OwnerSchemaStatus(settings.owner, _head(settings.owner), False, _verify(conn, settings))
