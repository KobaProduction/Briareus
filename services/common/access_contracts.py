from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import ClassVar, Literal, Self
from uuid import uuid4

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from service_runtime._field_serialization import iso_timestamp, uuid_hex

AccessLevel = Literal["read_only", "full_access"]
AccountScope = Literal["none", "all", "selected"]
SessionStatus = Literal["active", "revoked", "expired"]
EnforcementMode = Literal["unrestricted", "session_enforced"]
RequestKind = Literal["full_access", "extension"]


class OAuthContext(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=512)
    oauth_session_id: str = Field(min_length=1, max_length=128)


class SessionOpenRequest(OAuthContext):
    surface_id: int
    label: str = Field("", max_length=256)


class SessionValidateRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field("", max_length=256)
    tool_name: str = Field("", max_length=256)
    requires_full_access: bool = False
    account_id: str = Field("", max_length=256)


class SessionUpdateRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)
    label: str = Field("", max_length=256)


class FullAccessRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)
    account_scope: AccountScope = "none"
    account_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("account_ids")
    @classmethod
    def _normalize_account_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ExtensionRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)
    requested_expires_at: int = Field(ge=0)


class AdminSessionUpdate(BaseModel):
    admin_user_id: str = Field(min_length=1, max_length=128)
    access_level: AccessLevel | None = None
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = Field(default=None, max_length=100)
    expires_at: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=256)

    @field_validator("account_ids")
    @classmethod
    def _normalize_account_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class AdminSessionOwnerRequest(BaseModel):
    admin_user_id: str = Field(min_length=1, max_length=128)


class AdminResolveRequest(BaseModel):
    admin_user_id: str = Field(min_length=1, max_length=128)
    approve: bool
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = Field(default=None, max_length=100)
    expires_at: int | None = Field(default=None, ge=0)


class SurfaceControlUpdate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    surface_id: int
    mode: EnforcementMode


class SurfaceControlBatchUpdate(BaseModel):
    items: list[SurfaceControlUpdate] = Field(min_length=1, max_length=100)


class SessionSnapshot(BaseModel):
    id: str
    uid: str
    user_id: str
    oauth_client_id: str
    oauth_session_id: str
    surface_id: int
    access_level: AccessLevel
    account_scope: AccountScope
    account_ids: list[str]
    status: SessionStatus
    label: str
    expires_at: int


class ValidationResult(BaseModel):
    allowed: bool
    code: str
    session: SessionSnapshot | None = None
    retry_after_seconds: int = 0


class AccessRequestView(BaseModel):
    id: str
    session_id: str
    kind: RequestKind
    status: str
    requested_access_level: str
    requested_account_scope: AccountScope
    requested_account_ids: list[str]
    requested_expires_at: int


class AccessSessions(BaseModel):
    sessions: list[SessionSnapshot]


class AccessRequests(BaseModel):
    requests: list[AccessRequestView]


class SurfaceControlView(BaseModel):
    surface: str
    surface_id: int
    mode: EnforcementMode


class UserControlView(BaseModel):
    user_id: str
    surface_id: int
    mode: EnforcementMode


class SurfaceControls(BaseModel):
    controls: list[SurfaceControlView]


class UserControls(BaseModel):
    controls: list[UserControlView]


class ResolvedAccessRequest(BaseModel):
    request: AccessRequestView
    session: SessionSnapshot


class EmptyAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionLifecycleIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str
    surface_id: int
    user_id: str


class SessionOpenedDetails(SessionLifecycleIdentity):
    status: SessionStatus


class AccessRequestDetails(SessionLifecycleIdentity):
    request_id: str


class SessionClosedDetails(SessionLifecycleIdentity):
    """The existing close notification carries only its session identity."""


type AccessLifecycleType = Literal[
    "session_opened", "full_access_requested", "extension_requested", "session_closed"
]
type AccessLifecycleDetails = SessionOpenedDetails | AccessRequestDetails | SessionClosedDetails


class AccessLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    topic: Literal["access.sessions"] = "access.sessions"
    type: AccessLifecycleType
    event_id: UUID4 = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: AccessLifecycleDetails

    @model_validator(mode="after")
    def matching_details(self) -> Self:
        match self.type:
            case "session_opened":
                valid = isinstance(self.data, SessionOpenedDetails)
            case "session_closed":
                valid = isinstance(self.data, SessionClosedDetails)
            case "full_access_requested" | "extension_requested":
                valid = isinstance(self.data, AccessRequestDetails)
        if not valid:
            raise ValueError("Access lifecycle details do not match their event type")
        return self

    hex_event_id: ClassVar[Callable[[UUID4], str]] = field_serializer("event_id")(
        staticmethod(uuid_hex)
    )

    iso_occurred_at: ClassVar[Callable[[datetime], str]] = field_serializer("occurred_at")(
        staticmethod(iso_timestamp)
    )


class AccessLifecyclePublication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str
    event: AccessLifecycleEvent
