from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from briareus_json_values import JsonValue
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from control_panel_api.application.services import (
    AccountService,
    ControlPanelConfigService,
    InvocationAuditService,
    RuntimeSettingsService,
    SnapshotService,
)
from control_panel_api.domain.accounts import Account, AuthType, Provider
from control_panel_api.infrastructure.files import FileAdminStore
from control_panel_api.infrastructure.reverse import ReverseAdminClient
from control_panel_api.infrastructure.snapshot_worker import SnapshotRefresher
from control_panel_api.infrastructure.terminal import TerminalAdminClient
from control_panel_api.infrastructure.web import WebAdminClient
from control_panel_api.realtime import RealtimeBus
from control_panel_api.telemetry_ingest import FrontendTelemetryProxy


def _encode_call_cursor(occurred_at: datetime, invocation_id: str) -> str:
    payload = json.dumps(
        [occurred_at.astimezone(UTC).isoformat(), invocation_id], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_call_cursor(value: str) -> tuple[datetime, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError("invalid cursor payload")
        occurred_at = datetime.fromisoformat(str(decoded[0]))
        invocation_id = str(decoded[1]).strip()
        if not invocation_id:
            raise ValueError("invalid cursor id")
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)
        return (occurred_at, invocation_id)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid calls cursor") from exc


@dataclass(frozen=True)
class WebApiServices:
    accounts: AccountService
    audit: InvocationAuditService
    snapshots: SnapshotService
    config: ControlPanelConfigService
    runtime_settings: RuntimeSettingsService
    files: FileAdminStore
    reverse: ReverseAdminClient
    terminal: TerminalAdminClient
    web: WebAdminClient
    snapshot_refresher: SnapshotRefresher
    realtime: RealtimeBus | None = None
    telemetry: FrontendTelemetryProxy | None = None


class AccountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str
    provider: Provider
    auth_type: AuthType
    base_url: str = ""
    external_id: str = ""
    verify_tls: bool = True
    ca_cert_pem: str = ""
    enabled: bool = True
    credential: str = ""


class AccountUpdatePayload(AccountPayload):
    expected_updated_at: datetime | None = None


class AccountCandidatePayload(AccountPayload):
    alias: str = Field(min_length=1, max_length=128)
    base_url: str = Field("", max_length=2048)
    external_id: str = Field("", max_length=512)
    ca_cert_pem: str = Field("", max_length=65536)
    credential: str = Field("", max_length=131072)
    account_id: str = Field("", max_length=36)
    draft_revision: str = Field(min_length=1, max_length=128)


class ProjectCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    parent_dir: str = ""


class WorkerControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class WorkerHeapPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_heap_mb: int = Field(ge=128, le=32768)


class WorkerRecoverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: float = Field(4.0, ge=1.0, le=30.0)


class ViewportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: str = Field(min_length=1, max_length=255)
    width: int = Field(ge=320, le=7680)
    height: int = Field(ge=240, le=4320)


class BrowserThemePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color_scheme: str = Field(pattern="^(system|light|dark)$")


class BrowserTabPolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_tabs: int = Field(ge=1, le=100)
    idle_close_enabled: bool
    idle_timeout_seconds: int = Field(ge=30, le=86400)


class BrowserRemoteDebugPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: str = Field(min_length=1, max_length=255)


class FrontendTelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[JsonValue] = Field(min_length=1, max_length=500)


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field("", max_length=64)
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = Field(30, ge=1, le=3650)
    logging_max_records: int = Field(10000, ge=100, le=1000000)
    maintenance_interval_minutes: int = Field(60, ge=1, le=1440)
    terminal_max_exec_timeout_seconds: int = Field(21600, ge=1, le=86400)
    terminal_max_job_runtime_seconds: int = Field(43200, ge=1, le=604800)
    mcp_call_timeout_seconds: int = Field(0, ge=0, le=300)
    browser_external_enabled: bool = False
    browser_external_mcp_url: str = Field("", max_length=2048)
    browser_call_timeout_seconds: int = Field(300, ge=1, le=1800)
    browser_auto_disconnect_enabled: bool = False
    browser_idle_timeout_seconds: int = Field(300, ge=30, le=86400)
    browser_profile_dir_name: str = Field("Default", min_length=1, max_length=128)
    browser_extension_token: str = Field("", max_length=4096)
    browser_clear_extension_token: bool = False
    github_local_first_guidance: bool = True
    github_local_git_transport_enabled: bool = True
    github_remote_source_mutations_enabled: bool = False
    gitlab_local_first_guidance: bool = True
    gitlab_local_git_transport_enabled: bool = True
    gitlab_remote_source_mutations_enabled: bool = False
    reverse_idle_timeout_seconds: float = Field(900.0, ge=0, le=86400)


def _account_from_payload(payload: AccountPayload, *, existing: Account | None = None) -> Account:
    values: dict[str, object] = {
        "alias": payload.alias,
        "provider": payload.provider,
        "auth_type": payload.auth_type,
        "base_url": payload.base_url,
        "external_id": payload.external_id,
        "verify_tls": payload.verify_tls,
        "ca_cert_pem": payload.ca_cert_pem,
        "enabled": payload.enabled,
    }
    if existing is not None:
        values.update(
            id=existing.id, created_at=existing.created_at, updated_at=existing.updated_at
        )
    return Account.model_validate(values)
