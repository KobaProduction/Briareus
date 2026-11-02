"""Resources persistence for Node-owned execution facts, separate from desired intent."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from common.platform_db import CatalogBase


class NodePairIntentRow(CatalogBase):
    __tablename__ = "node_pair_intents"
    __table_args__ = ({"schema": "resources"},)
    operation_uuid: Mapped[UUID] = mapped_column(primary_key=True)
    node_uuid: Mapped[UUID] = mapped_column(ForeignKey("resources.nodes.id", ondelete="RESTRICT"))
    public_key: Mapped[str] = mapped_column(Text)
    actor_uuid: Mapped[UUID] = mapped_column()
    project_uuid: Mapped[UUID] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(String(64))
    expected_sequence: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NodeJournalLeaseRow(CatalogBase):
    __tablename__ = "node_journal_leases"
    __table_args__ = (
        CheckConstraint("epoch > 0 AND cursor >= 0", name="ck_node_journal_lease_counters"),
        {"schema": "resources"},
    )
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    session_uuid: Mapped[UUID] = mapped_column()
    epoch: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[int] = mapped_column(BigInteger, default=0)


class NodeJournalOperationRow(CatalogBase):
    __tablename__ = "node_journal_operations"
    __table_args__ = (
        UniqueConstraint(
            "node_uuid", "placement_uuid", "sequence", name="uq_node_journal_sequence"
        ),
        CheckConstraint("sequence > 0", name="ck_node_journal_operation_sequence"),
        CheckConstraint(
            "phase IN ('queued','pulling','stopping','creating','checking','rolling_back',"
            "'succeeded','failed')",
            name="ck_node_journal_operation_phase",
        ),
        Index(
            "uq_node_journal_active",
            "node_uuid",
            "placement_uuid",
            unique=True,
            postgresql_where=text("phase NOT IN ('succeeded','failed')"),
        ),
        {"schema": "resources"},
    )
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    operation_uuid: Mapped[UUID] = mapped_column(primary_key=True)
    placement_uuid: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(BigInteger)
    desired: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(16))
    previous: Mapped[str | None] = mapped_column(Text)
    container: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(64))
    diagnostic: Mapped[str | None] = mapped_column(Text)


class NodeJournalAppliedRow(CatalogBase):
    __tablename__ = "node_journal_applied"
    __table_args__ = ({"schema": "resources"},)
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    placement_uuid: Mapped[UUID] = mapped_column(primary_key=True)
    spec: Mapped[str] = mapped_column(Text)
    container: Mapped[str] = mapped_column(Text)


class NodeJournalConfigurationRow(CatalogBase):
    __tablename__ = "node_journal_configuration"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_node_journal_configuration_sequence"),
        {"schema": "resources"},
    )
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger)
    record: Mapped[str] = mapped_column(Text)


class NodeJournalAdmissionRow(CatalogBase):
    __tablename__ = "node_journal_admissions"
    __table_args__ = ({"schema": "resources"},)
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    request_uuid: Mapped[UUID] = mapped_column(primary_key=True)
    expires_at: Mapped[int] = mapped_column(BigInteger)


class NodeJournalEventRow(CatalogBase):
    __tablename__ = "node_journal_events"
    __table_args__ = ({"schema": "resources"},)
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    cursor: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    topic: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NodeJournalRequestRow(CatalogBase):
    __tablename__ = "node_journal_requests"
    __table_args__ = ({"schema": "resources"},)
    node_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    request_uuid: Mapped[UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int] = mapped_column(BigInteger)
