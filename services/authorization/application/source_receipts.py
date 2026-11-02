"""Named receipts for the existing signed multi-owner Access source protocol."""

from pydantic import BaseModel


class SourceSessionOpened(BaseModel):
    session_uuid: str
    project_id: str
    expires_at: str
    revision: int


class SourceSessionRevoked(BaseModel):
    session_uuid: str
    version: int
    status: str


class SourceElevationRequested(BaseModel):
    request_id: str
    version: int
    status: str


class SourceElevationResolved(BaseModel):
    approval_id: str
    status: str
    version: int
    issued_session_uuid: str | None
