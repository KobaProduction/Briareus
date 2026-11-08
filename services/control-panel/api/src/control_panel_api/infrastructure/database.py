from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class GitHubAccountRecord(Base):
    __tablename__ = "github_accounts"
    __allow_unmapped__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32))
    app_id: Mapped[str] = mapped_column(String(512), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    encrypted_credential: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    _credential_input: str = ""

    @property
    def credential_input(self) -> str:
        return ""

    @credential_input.setter
    def credential_input(self, value: str) -> None:
        self._credential_input = value


class GitLabAccountRecord(Base):
    __tablename__ = "gitlab_accounts"
    __allow_unmapped__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(2048), default="https://gitlab.com")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_cert_pem: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    encrypted_credential: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    _credential_input: str = ""

    @property
    def credential_input(self) -> str:
        return ""

    @credential_input.setter
    def credential_input(self, value: str) -> None:
        self._credential_input = value


class SigNozAccountRecord(Base):
    __tablename__ = "signoz_accounts"
    __allow_unmapped__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32), default="signoz_api_key")
    base_url: Mapped[str] = mapped_column(String(2048))
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_cert_pem: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    encrypted_credential: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    _credential_input: str = ""

    @property
    def credential_input(self) -> str:
        return ""

    @credential_input.setter
    def credential_input(self, value: str) -> None:
        self._credential_input = value


class CoolifyAccountRecord(Base):
    __tablename__ = "coolify_accounts"
    __allow_unmapped__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32), default="coolify_api_token")
    base_url: Mapped[str] = mapped_column(String(2048))
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_cert_pem: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    encrypted_credential: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    _credential_input: str = ""

    @property
    def credential_input(self) -> str:
        return ""

    @credential_input.setter
    def credential_input(self, value: str) -> None:
        self._credential_input = value


class InvocationRecord(Base):
    __tablename__ = "invocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    module: Mapped[str] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(256), index=True)
    account_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    provider: Mapped[str] = mapped_column(String(32), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    duration_ms: Mapped[float] = mapped_column(Float)
    error_type: Mapped[str] = mapped_column(String(256), default="")
    arguments_json: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(index=True, default=lambda: datetime.now(UTC))


class CachedSnapshotRecord(Base):
    __tablename__ = "cached_snapshots"
    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    refresh_after_seconds: Mapped[int] = mapped_column(Integer, default=300)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    updated_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    attempted_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    error_type: Mapped[str] = mapped_column(String(256), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ControlPanelConfigRecord(Base):
    __tablename__ = "management_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    logging_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    logging_capture_payloads: Mapped[bool] = mapped_column(Boolean, default=True)
    logging_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    logging_max_records: Mapped[int] = mapped_column(Integer, default=10000)
    maintenance_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)


class RuntimeSettingsRecord(Base):
    __tablename__ = "runtime_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    terminal_max_exec_timeout_seconds: Mapped[int] = mapped_column(Integer, default=21600)
    terminal_max_job_runtime_seconds: Mapped[int] = mapped_column(Integer, default=43200)


class McpRuntimeSettingsRecord(Base):
    __tablename__ = "mcp_runtime_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    call_timeout_seconds: Mapped[int] = mapped_column(Integer, default=0)


class GitHubRuntimeSettingsRecord(Base):
    __tablename__ = "github_runtime_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    local_first_guidance: Mapped[bool] = mapped_column(Boolean, default=True)
    local_git_transport_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remote_source_mutations_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class GitLabRuntimeSettingsRecord(Base):
    __tablename__ = "gitlab_runtime_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    local_first_guidance: Mapped[bool] = mapped_column(Boolean, default=True)
    local_git_transport_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remote_source_mutations_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class BrowserRuntimeSettingsRecord(Base):
    __tablename__ = "browser_runtime_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    external_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    external_mcp_url: Mapped[str] = mapped_column(String(2048), default="")
    call_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    auto_disconnect_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    profile_dir_name: Mapped[str] = mapped_column(String(128), default="Default")
    encrypted_extension_token: Mapped[str] = mapped_column(Text, default="")


def create_database(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    if make_url(database_url).drivername != "postgresql+psycopg":
        raise ValueError("Control Panel runtime requires PostgreSQL with the psycopg driver")
    engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True)
    return (engine, sessionmaker(bind=engine, expire_on_commit=False))
