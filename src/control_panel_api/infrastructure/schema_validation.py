"""Fail closed when a database schema differs from its declared owner schema."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, MetaData, inspect


def validate_schema(connection: Connection, metadata: MetaData) -> None:
    inspector = inspect(connection)
    actual = set(inspector.get_table_names()) - {"alembic_version"}
    if actual != set(metadata.tables):
        raise RuntimeError("Control Panel schema has unexpected or missing tables")
    for table in metadata.sorted_tables:
        primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
        if tuple(primary_key) != tuple(column.name for column in table.primary_key.columns):
            raise RuntimeError(f"Control Panel schema primary key mismatch: {table.name}")
        if inspector.get_check_constraints(table.name):
            raise RuntimeError(f"Control Panel schema has unexpected checks: {table.name}")
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    if compare_metadata(context, metadata):
        raise RuntimeError("Control Panel schema differs from its Alembic revision")
