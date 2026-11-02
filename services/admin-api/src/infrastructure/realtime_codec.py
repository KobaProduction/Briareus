"""Validate and serialize the existing administration/Valkey event protocol."""

import json
from collections.abc import Callable
from dataclasses import is_dataclass
from datetime import UTC, datetime
from typing import ClassVar, Final
from uuid import UUID, uuid4

from application.analysis_views import (
    AnalysisProjectDeleted,
    AnalysisProjectOpened,
    AnalysisProjectReleased,
    AnalysisWorkerChanged,
)
from application.dashboard_state import DashboardState
from application.panel_views import (
    CallsDeleted,
    ItemDeleted,
    RecordsRemoved,
    SettingsSnapshot,
    WorkerQueueClearedView,
    WorkerRecoveredView,
)
from application.realtime_details import RealtimeDetails
from application.terminal_views import JobCleanup, JobDeleted, JobStatus, WorkspaceDeleted
from application.web_session_contracts import WebSessionRevoked, WebUserControls
from domain.realtime import (
    AccountIdentity,
    AccountVerified,
    BrowserDebugIssued,
    BrowserPolicyFailure,
    BrowserUnavailable,
    MetricsHeartbeat,
    validate_topic,
)
from domain.telemetry import InvocationBatch
from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationInfo,
    field_serializer,
    field_validator,
)

from common.access_contracts import (
    AccessRequestDetails,
    ResolvedAccessRequest,
    SessionClosedDetails,
    SessionOpenedDetails,
    SessionSnapshot,
)
from common.account_contracts import AccountPublic
from common.audit_payloads import redact_json
from common.browser_contracts import BrowserStatus, ExternalBrowserStatus, PageSummary
from modules.workspace_compat.domain.receipts import (
    WorkspaceDelete,
    WorkspaceDirectoryEntry,
    WorkspaceFileEntry,
)
from service_runtime._field_serialization import uuid_hex

REALTIME_VERSION: Final[int] = 1

_DETAIL_SCHEMAS: dict[tuple[str, str], TypeAdapter[RealtimeDetails]] = {
    ("mcp.calls", "batch"): TypeAdapter(InvocationBatch),
    ("mcp.calls", "snapshot"): TypeAdapter(InvocationBatch),
    ("system.metrics", "heartbeat"): TypeAdapter(MetricsHeartbeat),
    ("system.metrics", "snapshot"): TypeAdapter(DashboardState),
    ("browser.runtime", "snapshot"): TypeAdapter(BrowserStatus | BrowserUnavailable),
    ("browser.runtime", "theme.changed"): TypeAdapter(BrowserStatus),
    ("browser.runtime", "viewport.changed"): TypeAdapter(PageSummary),
    ("browser.runtime", "remote_debug.issued"): TypeAdapter(BrowserDebugIssued),
    ("browser.runtime", "external.connected"): TypeAdapter(ExternalBrowserStatus),
    ("browser.runtime", "external.disconnected"): TypeAdapter(ExternalBrowserStatus),
    ("browser.runtime", "external.reset"): TypeAdapter(ExternalBrowserStatus),
    ("browser.runtime", "external.policy_disconnect_failed"): TypeAdapter(BrowserPolicyFailure),
    ("access.sessions", "session_opened"): TypeAdapter(SessionOpenedDetails),
    ("access.sessions", "session_closed"): TypeAdapter(SessionClosedDetails),
    ("access.sessions", "full_access_requested"): TypeAdapter(AccessRequestDetails),
    ("access.sessions", "extension_requested"): TypeAdapter(AccessRequestDetails),
    ("access.sessions", "request_resolved"): TypeAdapter(ResolvedAccessRequest),
    ("access.sessions", "session_updated"): TypeAdapter(SessionSnapshot),
    ("access.sessions", "session_revoked"): TypeAdapter(WebSessionRevoked),
    ("access.sessions", "controls_changed"): TypeAdapter(WebUserControls),
    ("admin.events", "account.created"): TypeAdapter(AccountPublic),
    ("admin.events", "account.updated"): TypeAdapter(AccountPublic),
    ("admin.events", "account.deleted"): TypeAdapter(AccountIdentity),
    ("admin.events", "account.verified"): TypeAdapter(AccountVerified),
    ("admin.events", "calls.cleared"): TypeAdapter(CallsDeleted),
    ("admin.events", "calls.deleted"): TypeAdapter(ItemDeleted),
    ("admin.events", "calls.retention_applied"): TypeAdapter(RecordsRemoved),
    ("admin.events", "files.uploaded"): TypeAdapter(WorkspaceFileEntry),
    ("admin.events", "files.directory_created"): TypeAdapter(WorkspaceDirectoryEntry),
    ("admin.events", "files.deleted"): TypeAdapter(WorkspaceDelete),
    ("admin.events", "terminal.job.cancelled"): TypeAdapter(JobStatus),
    ("admin.events", "terminal.job.deleted"): TypeAdapter(JobDeleted),
    ("admin.events", "terminal.jobs.cleaned"): TypeAdapter(JobCleanup),
    ("admin.events", "terminal.workspace.deleted"): TypeAdapter(WorkspaceDeleted),
    ("admin.events", "analysis.project.created"): TypeAdapter(AnalysisProjectOpened),
    ("admin.events", "analysis.project.opened"): TypeAdapter(AnalysisProjectOpened),
    ("admin.events", "analysis.project.released"): TypeAdapter(AnalysisProjectReleased),
    ("admin.events", "analysis.project.deleted"): TypeAdapter(AnalysisProjectDeleted),
    ("admin.events", "analysis.worker.routing_changed"): TypeAdapter(AnalysisWorkerChanged),
    ("admin.events", "analysis.worker.clear_queue"): TypeAdapter(WorkerQueueClearedView),
    ("admin.events", "analysis.worker.recover"): TypeAdapter(WorkerRecoveredView),
    ("admin.events", "settings.updated"): TypeAdapter(SettingsSnapshot),
}

_SPARSE_EVENTS = frozenset(
    {
        ("browser.runtime", "theme.changed"),
        ("browser.runtime", "viewport.changed"),
        ("browser.runtime", "external.connected"),
        ("browser.runtime", "external.disconnected"),
        ("browser.runtime", "external.reset"),
        ("admin.events", "analysis.project.created"),
        ("admin.events", "analysis.project.opened"),
        ("admin.events", "analysis.project.released"),
        ("admin.events", "analysis.project.deleted"),
        ("admin.events", "analysis.worker.routing_changed"),
        ("admin.events", "analysis.worker.clear_queue"),
        ("admin.events", "analysis.worker.recover"),
    }
)


class RealtimeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    topic: str
    type: str
    event_id: UUID
    occurred_at: datetime
    data: RealtimeDetails

    hex_event_id: ClassVar[Callable[[UUID], str]] = field_serializer("event_id")(
        staticmethod(uuid_hex)
    )

    @field_validator("topic")
    @classmethod
    def supported_topic(cls, value: str) -> str:
        return validate_topic(value)

    @field_validator("data", mode="before")
    @classmethod
    def event_details(cls, value: object, info: ValidationInfo[None]) -> RealtimeDetails:
        topic, event_type = info.data.get("topic"), info.data.get("type")
        if not isinstance(topic, str) or not isinstance(event_type, str):
            raise ValueError("Realtime topic and type are required")
        schema = _DETAIL_SCHEMAS.get((topic, event_type))
        if schema is None:
            raise ValueError("Unsupported realtime event contract")
        if isinstance(value, BaseModel) or is_dataclass(value):
            return schema.validate_python(value)
        # This is the raw Pydantic JSON boundary, not an application data contract.
        return schema.validate_json(json.dumps(value, ensure_ascii=False, allow_nan=False))


class RealtimePublication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    event: RealtimeEnvelope


def _include_defaults(model: BaseModel) -> None:
    model.model_fields_set.update(type(model).model_fields)
    for name in type(model).model_fields:
        child = getattr(model, name)
        if isinstance(child, BaseModel):
            _include_defaults(child)
        elif isinstance(child, (tuple, list)):
            for item in child:
                if isinstance(item, BaseModel):
                    _include_defaults(item)


def new_event(topic: str, event_type: str, details: RealtimeDetails) -> RealtimeEnvelope:
    topic = validate_topic(topic)
    if isinstance(details, InvocationBatch) and event_type == "batch":
        adapter = TypeAdapter(InvocationBatch)
        raw = adapter.dump_python(details, mode="json")
        details = adapter.validate_json(redact_json(raw))
    if isinstance(details, BaseModel):
        details = details.model_copy(deep=True)
        if (topic, event_type) not in _SPARSE_EVENTS:
            _include_defaults(details)
    return RealtimeEnvelope(
        version=REALTIME_VERSION,
        topic=topic,
        type=event_type,
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        data=details,
    )


def snapshot_event(event: RealtimeEnvelope) -> RealtimeEnvelope:
    return event.model_copy(
        update={"type": "snapshot", "event_id": uuid4(), "occurred_at": datetime.now(UTC)}
    )


def event_json(event: RealtimeEnvelope) -> str:
    return event.model_dump_json(exclude_unset=True)
