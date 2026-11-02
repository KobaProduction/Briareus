"""Unchanged internal API response shapes, including OAuth timestamp formatting."""

from datetime import datetime
from typing import Self

from domain.oauth_sessions import OAuthSession
from pydantic import BaseModel, Field, field_serializer

from common.account_contracts import AuthenticatedReaderView as AuthenticatedReaderView

from .invocation_contracts import InvocationDocument


class InvocationList(BaseModel):
    events: list[InvocationDocument]
    count: int = Field(ge=0)


class OAuthSessionView(BaseModel):
    id: str
    client_id: str
    client_name: str
    resource: str
    login: str
    subject: str
    scopes: list[str]
    status: str
    last_event: str
    access_jti: str
    refresh_jti: str
    previous_refresh_jti: str
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    last_used_at: datetime | None
    last_refresh_at: datetime | None
    revoked_at: datetime | None
    error_type: str
    error_message: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, session: OAuthSession) -> Self:
        return cls.model_validate(session, from_attributes=True, strict=True)

    @field_serializer(
        "access_expires_at",
        "refresh_expires_at",
        "last_used_at",
        "last_refresh_at",
        "revoked_at",
        "created_at",
        "updated_at",
        when_used="json",
    )
    def wire_timestamp(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None


class OAuthSessionList(BaseModel):
    sessions: list[OAuthSessionView]
    count: int = Field(ge=0)
