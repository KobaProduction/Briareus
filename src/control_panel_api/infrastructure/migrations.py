from __future__ import annotations

from pathlib import Path
from typing import TextIO

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

from control_panel_api.infrastructure.database import Base
from control_panel_api.infrastructure.schema_validation import validate_schema

_MIGRATION_LOCK = 7_109_453_619_238


def migration_config(
    connection: Connection | None = None, *, output_buffer: TextIO | None = None
) -> Config:
    """Configure packaged revisions for normal Alembic commands and authoring."""
    config = Config(output_buffer=output_buffer)
    location = Path(__file__).resolve().with_name("alembic")
    config.set_main_option("script_location", str(location))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def run_migrations(engine: Engine) -> None:
    """Apply revisions atomically, serializing concurrent application startups."""
    if engine.dialect.name != "postgresql":
        raise ValueError("Control Panel schema migrations require PostgreSQL")
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK})
        command.upgrade(migration_config(connection), "head")
        validate_schema(connection, Base.metadata)
