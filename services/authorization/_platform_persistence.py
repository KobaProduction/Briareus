"""Fresh Authorization command ledger and immutable security audit."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from authorization.infrastructure.journal_records import (
    ACCESS_OUTBOX_EVENT,
    AUDIT_DETAILS,
    AccessOutboxEvent,
    AuditDetails,
    NoAuditDetails,
)
from common.infrastructure.record_jsonb import RecordJSONB
from common.platform_db import AccessBase


class IdempotencyRow(AccessBase):
    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint("status IN ('pending','completed')", name="ck_idempotency_status"),
        UniqueConstraint(
            "actor_scope",
            "project_scope",
            "operation",
            "key",
            name="uq_authorization_command_idempotency",
        ),
        Index("ix_authorization_command_expiry", "expires_at"),
        {"schema": "access"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_scope: Mapped[str] = mapped_column(String(64))
    project_scope: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(128))
    key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_ciphertext: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SecurityAuditRow(AccessBase):
    __tablename__ = "audit"
    __table_args__ = (
        Index("ix_authorization_audit_actor_time", "actor_id", "created_at"),
        {"schema": "access"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column()
    project_id: Mapped[UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(128))
    object_id: Mapped[str] = mapped_column(String(128))
    details: Mapped[AuditDetails] = mapped_column(
        RecordJSONB(AUDIT_DETAILS, exclude_none=False, exclude_unset=True),
        nullable=False,
        default=NoAuditDetails,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    @validates("details")
    def _audit_details(self, _key: str, value: object) -> AuditDetails:
        return AUDIT_DETAILS.validate_python(value)


class OutboxRow(AccessBase):
    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_auth_outbox_pending", "published_at", "created_at"),
        {"schema": "access"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_name: Mapped[str] = mapped_column(String(128))
    event_payload: Mapped[AccessOutboxEvent] = mapped_column(
        RecordJSONB(ACCESS_OUTBOX_EVENT, exclude_none=False, exclude_unset=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_id: Mapped[UUID | None] = mapped_column()
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    @validates("event_payload")
    def _event_record(self, _key: str, value: object) -> AccessOutboxEvent:
        return ACCESS_OUTBOX_EVENT.validate_python(value)
