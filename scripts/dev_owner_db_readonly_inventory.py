#!/usr/bin/env python3
"""Inventory ONE approved Development owner DB without reading row contents.

No mutations, no secrets in output, no provider/other database connection.
Never interprets rows/version as authorization to wipe an owner database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy import table as sql_table
from sqlalchemy.sql import quoted_name

if TYPE_CHECKING:
    from asyncpg import Connection, Record

_OWNERS = {
    "access": "briareus_access",
    "platform": "briareus_platform",
    "resources": "briareus_resources",
}
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z", re.ASCII)
_REVISION = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,62}\Z", re.ASCII)
_MAX_TABLES = 96


class InventoryObserved(TypedDict):
    status: Literal["READ_ONLY_SNAPSHOT_OBSERVED"]
    owner: str
    logical_database: str
    revision: str | None
    revision_verified: bool
    schema_count: int
    ordinary_data_tables: int
    nonempty_tables: int
    exact_data_row_count: int
    unsupported_catalog_objects: int
    catalog_complete: bool
    full_product_or_files_root_dependency_verified: Literal[False]
    approved_for_reset: Literal[False]
    mutations_performed: Literal[False]


class InventoryUnverified(TypedDict):
    status: Literal["READ_ONLY_INVENTORY_UNVERIFIED"]
    owner: str
    approved_for_reset: Literal[False]
    mutations_performed: Literal[False]


class MigrationVersionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version_num: StrictStr


class TableCardinality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    count: int = Field(strict=True, ge=0)


@dataclass(frozen=True)
class ObservedRevision:
    revision: str | None
    verified: bool


@dataclass(frozen=True)
class CatalogCounts:
    schema_count: int
    ordinary_tables: int
    nonempty_tables: int
    total_rows: int
    unsupported_objects: int


async def _observed_revision(connection: Connection, has_version: bool) -> ObservedRevision:
    if has_version:
        versions = await connection.fetch("SELECT version_num FROM public.alembic_version LIMIT 3")
        if len(versions) == 1:
            try:
                row = MigrationVersionRow.model_validate(dict(versions[0]))
            except ValidationError:
                return ObservedRevision(None, False)
            if _REVISION.fullmatch(row.version_num):
                return ObservedRevision(row.version_num, True)
    return ObservedRevision(None, False)


async def _table_cardinality(connection: Connection, schema: str, table: str) -> int:
    relation = sql_table(quoted_name(table, True), schema=quoted_name(schema, True))
    statement = select(func.count()).select_from(relation)
    query = str(statement.compile())
    try:
        row = TableCardinality.model_validate({"count": await connection.fetchval(query)})
    except ValidationError:
        raise ValueError("unverified table cardinality") from None
    return row.count


async def _catalog_counts(connection: Connection, objects: Sequence[Record]) -> CatalogCounts:
    total_rows = 0
    nonempty_tables = 0
    ordinary_tables = 0
    unsupported_objects = 0
    schema_names: set[str] = set()
    for item in objects:
        schema, table = item["schema_name"], item["object_name"]
        if not isinstance(schema, str) or not isinstance(table, str):
            raise ValueError("untrusted catalog identifiers")
        if not _IDENTIFIER.fullmatch(schema) or not _IDENTIFIER.fullmatch(table):
            raise ValueError("noncanonical owner catalog identifiers")
        schema_names.add(schema)
        if schema == "public" and table == "alembic_version":
            continue
        if item["object_kind"] != "r" or item["partition"]:
            unsupported_objects += 1
            continue
        # Count only; the validated identifiers remain quoted.
        count = await _table_cardinality(connection, schema, table)
        ordinary_tables += 1
        total_rows += count
        nonempty_tables += int(count > 0)
    return CatalogCounts(
        len(schema_names), ordinary_tables, nonempty_tables, total_rows, unsupported_objects
    )


async def inspect_connection(
    connection: Connection, owner: str, expected_principal: str
) -> InventoryObserved:
    """The caller owns transport. Read-only transaction; bounded catalog/row counts."""
    if owner not in _OWNERS or not _IDENTIFIER.fullmatch(expected_principal):
        raise ValueError("owner or role is not approved")
    database = _OWNERS[owner]
    async with connection.transaction(isolation="repeatable_read", readonly=True):
        identity = await connection.fetchrow(
            "SELECT current_database() AS db, current_user AS role"
        )
        if identity is None or identity["db"] != database or identity["role"] != expected_principal:
            raise ValueError("unexpected PostgreSQL database/principal")
        database_owner = await connection.fetchval(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()"
        )
        if database_owner != expected_principal:
            raise ValueError("owner logical database has a foreign PostgreSQL owner")
        has_version = bool(
            await connection.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        )
        revision = await _observed_revision(connection, has_version)
        objects = await connection.fetch(
            """SELECT n.nspname AS schema_name, c.relname AS object_name,
                      c.relkind::text AS object_kind, c.relispartition AS partition
               FROM pg_catalog.pg_class c
               JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                 AND c.relkind IN ('r','p','v','m','f','S')
               ORDER BY n.nspname, c.relname
               LIMIT 101"""
        )
        if len(objects) > _MAX_TABLES:
            raise ValueError("owner has more objects than the bounded inventory")
        counts = await _catalog_counts(connection, objects)
        return InventoryObserved(
            status="READ_ONLY_SNAPSHOT_OBSERVED",
            owner=owner,
            logical_database=database,
            revision=revision.revision,
            revision_verified=revision.verified,
            schema_count=counts.schema_count,
            ordinary_data_tables=counts.ordinary_tables,
            nonempty_tables=counts.nonempty_tables,
            exact_data_row_count=counts.total_rows,
            unsupported_catalog_objects=counts.unsupported_objects,
            catalog_complete=counts.unsupported_objects == 0
            and (revision.verified or not has_version),
            full_product_or_files_root_dependency_verified=False,
            approved_for_reset=False,
            mutations_performed=False,
        )


def _connection_contract(owner: str) -> tuple[str, str]:
    """Only existing per-application operator env and internal PG DNS."""
    if owner not in _OWNERS:
        raise ValueError("unknown owner")
    if os.environ.get("POSTGRES_HOST") != "briareus-postgres":
        raise ValueError("noncanonical internal PostgreSQL DNS")
    if os.environ.get("POSTGRES_PORT", "5432") != "5432":
        raise ValueError("noncanonical internal PostgreSQL port")
    db = _OWNERS[owner]
    if os.environ.get("POSTGRES_DB") != db:
        raise ValueError("PostgreSQL database not pinned to selected owner")
    user = os.environ.get("POSTGRES_USER", "")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not _IDENTIFIER.fullmatch(user) or not password or len(password) > 8192:
        raise ValueError("missing or malformed scoped PostgreSQL credentials")
    return user, password


async def _run(owner: str) -> InventoryObserved:
    user, password = _connection_contract(owner)
    import asyncpg

    conn = await asyncpg.connect(
        host="briareus-postgres",
        port=5432,
        database=_OWNERS[owner],
        user=user,
        password=password,
        timeout=5,
        server_settings={
            "application_name": "briareus_dev_owner_readonly_inventory",
            "default_transaction_read_only": "on",
            "statement_timeout": "1500",
        },
    )
    try:
        return await asyncio.wait_for(inspect_connection(conn, owner, user), timeout=16)
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", choices=sorted(_OWNERS), required=True)
    args = parser.parse_args()
    result: InventoryObserved | InventoryUnverified
    try:
        result = asyncio.run(_run(args.owner))
    except Exception:
        # Fail closed without leaking database errors, host or credentials.
        result = InventoryUnverified(
            status="READ_ONLY_INVENTORY_UNVERIFIED",
            owner=args.owner,
            approved_for_reset=False,
            mutations_performed=False,
        )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "READ_ONLY_SNAPSHOT_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
