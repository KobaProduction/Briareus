"""Bound concurrent managed terminal processes without altering existing policy values."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_terminal_concurrency"
down_revision: str | None = "0001_control_panel"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    column = sa.Column(
        "terminal_max_concurrent_processes", sa.Integer(), nullable=False, server_default="16"
    )
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("runtime_settings", recreate="always") as batch:
            batch.add_column(column)
            batch.alter_column("terminal_max_concurrent_processes", server_default=None)
    else:
        op.add_column("runtime_settings", column)
        op.alter_column(
            "runtime_settings", "terminal_max_concurrent_processes", server_default=None
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("runtime_settings", recreate="always") as batch:
            batch.drop_column("terminal_max_concurrent_processes")
    else:
        op.drop_column("runtime_settings", "terminal_max_concurrent_processes")
