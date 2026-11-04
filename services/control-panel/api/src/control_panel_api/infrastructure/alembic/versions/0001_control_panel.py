"""Initial immutable Control Panel PostgreSQL schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from control_panel_api.infrastructure.schema_validation import validate_schema

revision: str = "0001_control_panel"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def initial_metadata() -> sa.MetaData:
    """The revision snapshot is independent of future application models."""
    metadata = sa.MetaData()
    sa.Table(
        "browser_runtime_settings",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("external_enabled", sa.Boolean(), nullable=False),
        sa.Column("external_mcp_url", sa.String(length=2048), nullable=False),
        sa.Column("call_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("auto_disconnect_enabled", sa.Boolean(), nullable=False),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("profile_dir_name", sa.String(length=128), nullable=False),
        sa.Column("encrypted_extension_token", sa.Text(), nullable=False),
    )
    sa.Table(
        "cached_snapshots",
        metadata,
        sa.Column("key", sa.String(length=256), nullable=False, primary_key=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("refresh_after_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.Column("error_type", sa.String(length=256), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "coolify_accounts",
        metadata,
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), nullable=False),
        sa.Column("ca_cert_pem", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "github_accounts",
        metadata,
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("app_id", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "github_runtime_settings",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("local_first_guidance", sa.Boolean(), nullable=False),
        sa.Column("local_git_transport_enabled", sa.Boolean(), nullable=False),
        sa.Column("remote_source_mutations_enabled", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "gitlab_accounts",
        metadata,
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), nullable=False),
        sa.Column("ca_cert_pem", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "gitlab_runtime_settings",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("local_first_guidance", sa.Boolean(), nullable=False),
        sa.Column("local_git_transport_enabled", sa.Boolean(), nullable=False),
        sa.Column("remote_source_mutations_enabled", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "invocations",
        metadata,
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=256), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("error_type", sa.String(length=256), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "management_config",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("logging_enabled", sa.Boolean(), nullable=False),
        sa.Column("logging_capture_payloads", sa.Boolean(), nullable=False),
        sa.Column("logging_retention_days", sa.Integer(), nullable=False),
        sa.Column("logging_max_records", sa.Integer(), nullable=False),
        sa.Column("maintenance_interval_minutes", sa.Integer(), nullable=False),
    )
    sa.Table(
        "mcp_runtime_settings",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("call_timeout_seconds", sa.Integer(), nullable=False),
    )
    sa.Table(
        "runtime_settings",
        metadata,
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("terminal_max_exec_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("terminal_max_job_runtime_seconds", sa.Integer(), nullable=False),
    )
    sa.Table(
        "signoz_accounts",
        metadata,
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), nullable=False),
        sa.Column("ca_cert_pem", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    sa.Index(
        "ix_cached_snapshots_attempted_at",
        metadata.tables["cached_snapshots"].c["attempted_at"],
        unique=False,
    )
    sa.Index(
        "ix_cached_snapshots_category",
        metadata.tables["cached_snapshots"].c["category"],
        unique=False,
    )
    sa.Index(
        "ix_cached_snapshots_status", metadata.tables["cached_snapshots"].c["status"], unique=False
    )
    sa.Index(
        "ix_cached_snapshots_updated_at",
        metadata.tables["cached_snapshots"].c["updated_at"],
        unique=False,
    )
    sa.Index(
        "ix_coolify_accounts_alias", metadata.tables["coolify_accounts"].c["alias"], unique=True
    )
    sa.Index(
        "ix_coolify_accounts_enabled",
        metadata.tables["coolify_accounts"].c["enabled"],
        unique=False,
    )
    sa.Index("ix_github_accounts_alias", metadata.tables["github_accounts"].c["alias"], unique=True)
    sa.Index(
        "ix_github_accounts_enabled", metadata.tables["github_accounts"].c["enabled"], unique=False
    )
    sa.Index("ix_gitlab_accounts_alias", metadata.tables["gitlab_accounts"].c["alias"], unique=True)
    sa.Index(
        "ix_gitlab_accounts_enabled", metadata.tables["gitlab_accounts"].c["enabled"], unique=False
    )
    sa.Index(
        "ix_invocations_account_id", metadata.tables["invocations"].c["account_id"], unique=False
    )
    sa.Index("ix_invocations_module", metadata.tables["invocations"].c["module"], unique=False)
    sa.Index(
        "ix_invocations_occurred_at", metadata.tables["invocations"].c["occurred_at"], unique=False
    )
    sa.Index("ix_invocations_provider", metadata.tables["invocations"].c["provider"], unique=False)
    sa.Index(
        "ix_invocations_request_id", metadata.tables["invocations"].c["request_id"], unique=False
    )
    sa.Index("ix_invocations_status", metadata.tables["invocations"].c["status"], unique=False)
    sa.Index("ix_invocations_tool", metadata.tables["invocations"].c["tool"], unique=False)
    sa.Index("ix_signoz_accounts_alias", metadata.tables["signoz_accounts"].c["alias"], unique=True)
    sa.Index(
        "ix_signoz_accounts_enabled", metadata.tables["signoz_accounts"].c["enabled"], unique=False
    )
    return metadata


def upgrade() -> None:
    metadata = initial_metadata()
    if not op.get_context().as_sql:
        connection = op.get_bind()
        existing = set(sa.inspect(connection).get_table_names()) - {"alembic_version"}
        if existing:
            validate_schema(connection, metadata)
            return
    for table in metadata.sorted_tables:
        columns = [
            sa.Column(
                column.name, column.type, nullable=column.nullable, primary_key=column.primary_key
            )
            for column in table.columns
        ]
        op.create_table(table.name, *columns)
        for index in sorted(table.indexes, key=lambda item: str(item.name)):
            op.create_index(
                str(index.name),
                table.name,
                [column.name for column in index.columns],
                unique=index.unique,
            )


def downgrade() -> None:
    for table in reversed(initial_metadata().sorted_tables):
        for index in sorted(table.indexes, key=lambda item: str(item.name), reverse=True):
            op.drop_index(str(index.name), table_name=table.name)
        op.drop_table(table.name)
