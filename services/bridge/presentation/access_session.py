"""Session metadata sent to the external MCP result serializer."""

from pydantic import BaseModel

from common.access_contracts import AccessLevel, AccountScope, SessionStatus


class SessionMetadata(BaseModel):
    session_id: str
    status: SessionStatus
    access_level: AccessLevel
    expires_at: int
    account_scope: AccountScope


class AccessSessionError(BaseModel):
    error: str
    message: str
    retry_after_seconds: int | None = None
    detail: str | None = None
    access_session: SessionMetadata | None = None
