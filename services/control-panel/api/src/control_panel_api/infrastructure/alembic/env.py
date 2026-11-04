"""Use the caller's transaction, or render portable PostgreSQL DDL offline."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from control_panel_api.infrastructure.database import Base

if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError("Alembic online commands require an explicit PostgreSQL connection")
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()
