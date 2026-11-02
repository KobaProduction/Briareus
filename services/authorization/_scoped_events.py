"""Durable, scope-filtered realtime SOURCE ports (no network WS mount).

Outbox delivery is ingested into Project/Team/User streams with independent
monotone revisions and epochs. Consumers re-check current User/ownership/
membership on EVERY poll, including resumed polls; no global topic leaks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._platform_permissions import project_permit, team_permit
from authorization._platform_persistence import OutboxRow
from authorization._project_access import CallerPrincipal
from authorization._scoped_events_persistence import (
    ScopeCursorRow,
    ScopeDeliveryReceiptRow,
    ScopeEventRow,
)
from authorization._service_identity import (
    CurrentServiceDecisionValidator,
    ServiceAuthorizationDecision,
)
from authorization.application.outbox_delivery import DurableOutboxPublisher
from authorization.domain.outbox_delivery import ClaimedEvent
from authorization.domain.scoped_event_policy import KINDS as KINDS
from authorization.domain.scoped_event_policy import PUBLIC_DETAIL_KEYS as PUBLIC_DETAIL_KEYS
from authorization.domain.scoped_event_policy import (
    SECURITY_CHANGES,
    PublicScopePayload,
    ScopeIdentity,
)
from authorization.infrastructure.journal_records import AccessOutboxEvent, LegacySecurityEvent
from authorization.infrastructure.outbox_content import outbox_content_sha256
from authorization.infrastructure.scoped_event_codec import parse_scope_uuid as _parse_uuid
from authorization.infrastructure.scoped_event_codec import safe_scope_payload as _safe_payload
from authorization.infrastructure.scoped_event_codec import scope_provenance
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId, UserId
from identity._domain import UserRole

EVENT_RETENTION = timedelta(days=7)
SUBSCRIPTION_TTL = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class ScopeKey:
    kind: str
    scope_id: UUID

    def __post_init__(self) -> None:
        try:
            ScopeIdentity(self.kind, self.scope_id)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from None


@dataclass(frozen=True, slots=True)
class ScopeOffset:
    scope: ScopeKey
    epoch: UUID
    after_sequence: int


@dataclass(frozen=True, slots=True)
class ScopeSubscription:
    subscriber_id: UUID
    scope: ScopeKey
    actor_id: UserId
    decision_version: str
    offsets: tuple[ScopeOffset, ...]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ScopeEvent:
    event_id: UUID
    source_outbox_id: UUID
    scope: ScopeKey
    sequence: int
    epoch: UUID
    event_type: str
    actor_user_id: UUID | None
    payload: PublicScopePayload
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ScopeBatch:
    subscription: ScopeSubscription
    events: tuple[ScopeEvent, ...]
    resume_offsets: tuple[ScopeOffset, ...]


class ScopeResumeRequired(Conflict):
    code = "resume_required"


class ScopeAccessRevoked(AccessDenied):
    code = "scope_access_revoked"


def _scopes(event_name: str, raw: AccessOutboxEvent) -> tuple[ScopeKey, ...]:
    return tuple(
        ScopeKey(scope.kind, scope.scope_id) for scope in scope_provenance(raw).scopes(event_name)
    )


class ScopedEventFeed:
    def __init__(
        self,
        app: PlatformApplication,
        validator: CurrentServiceDecisionValidator | None = None,
    ) -> None:
        self.app = app
        self.validator = validator

    @staticmethod
    async def _cursor(tx: AsyncSession, scope: ScopeKey) -> ScopeCursorRow:
        await tx.execute(
            insert(ScopeCursorRow)
            .values(
                scope_kind=scope.kind,
                scope_id=scope.scope_id,
                epoch=uuid4(),
                revision=0,
            )
            .on_conflict_do_nothing(index_elements=["scope_kind", "scope_id"])
        )
        row = cast(
            ScopeCursorRow | None,
            await tx.scalar(
                select(ScopeCursorRow)
                .where(
                    ScopeCursorRow.scope_kind == scope.kind,
                    ScopeCursorRow.scope_id == scope.scope_id,
                )
                .with_for_update()
            ),
        )
        if row is None:
            raise RuntimeError("scope cursor missing after owner insert")
        return row

    async def ingest_outbox(
        self,
        tx: AsyncSession,
        outbox_id: UUID,
    ) -> int:
        """Idempotent durable fanout after an existing committed audit/outbox."""
        source = await tx.scalar(select(OutboxRow).where(OutboxRow.id == outbox_id))
        if source is None:
            raise InvalidInput("outbox source event is unavailable")
        event_name = source.event_name
        if not re.fullmatch(r"[a-z][a-z0-9_.]{1,127}", event_name):
            raise InvalidInput("outbox event type is not a public scope event")
        raw = source.event_payload
        clean = _safe_payload(raw)
        actor = (
            _parse_uuid(str(raw.actor_id))
            if isinstance(raw, LegacySecurityEvent) and raw.actor_id is not None
            else None
        )
        scopes = _scopes(event_name, raw)
        if event_name in SECURITY_CHANGES and not scopes:
            # Missing provenance is an integrity failure; do not mark the
            # durable audit event delivered while its revocation is unseen.
            raise InvalidInput("security event has no resolvable scope")
        inserted = 0
        for scope in scopes:
            # Serialized cursor lock ensures scope sequence matches COMMIT
            # order, unlike PostgreSQL global nextval under concurrency.
            cursor = await self._cursor(tx, scope)
            existing = await tx.scalar(
                select(ScopeEventRow.event_id).where(
                    ScopeEventRow.scope_kind == scope.kind,
                    ScopeEventRow.scope_id == scope.scope_id,
                    ScopeEventRow.source_outbox_id == outbox_id,
                )
            )
            if existing is not None:
                continue
            cursor.revision += 1
            if event_name in SECURITY_CHANGES:
                cursor.epoch = uuid4()
            cursor.updated_at = datetime.now(UTC)
            tx.add(
                ScopeEventRow(
                    event_id=uuid4(),
                    scope_kind=scope.kind,
                    scope_id=scope.scope_id,
                    sequence=cursor.revision,
                    epoch=cursor.epoch,
                    source_outbox_id=outbox_id,
                    event_type=event_name,
                    actor_user_id=actor,
                    safe_payload=clean,
                    created_at=source.created_at,
                    expires_at=datetime.now(UTC) + EVENT_RETENTION,
                )
            )
            await tx.flush()
            inserted += 1
        return inserted

    async def _authorize_subscription(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        scope: ScopeKey,
    ) -> tuple[str, tuple[ScopeKey, ...]]:
        # Serialize against User revocation and Project/Team owner changes
        # while constructing the filtered snapshot in this SQL transaction.
        actor = await self.app.current_user(tx, caller, lock=True)
        if scope.kind == "user":
            if scope.scope_id != caller.user_id and actor.role is not UserRole.SUPERUSER:
                raise ScopeAccessRevoked("User event scope access denied")
            return (
                f"user-v1:{actor.id}:{actor.credential_version}:{actor.role.value}",
                (scope,),
            )
        if scope.kind == "team":
            team = await self.app.teams.get(tx, TeamId(scope.scope_id), lock=True)
            if team is None:
                raise ScopeAccessRevoked("Team event scope unavailable")
            permit = await team_permit(tx, self.app, caller, TeamId(scope.scope_id))
            return permit.decision_version, (scope,)
        project = await self.app.projects.get(tx, PlatformProjectId(scope.scope_id), lock=True)
        if project is None:
            raise ScopeAccessRevoked("Project event scope unavailable")
        if project.owner_team_id is not None:
            team = await self.app.teams.get(tx, TeamId(project.owner_team_id), lock=True)
            if team is None:
                raise ScopeAccessRevoked("owning Team event scope unavailable")
        project_decision = await project_permit(
            tx, self.app, caller, PlatformProjectId(scope.scope_id)
        )
        if project.owner_team_id is not None:
            return (
                project_decision.decision_version,
                (scope, ScopeKey("team", project.owner_team_id)),
            )
        return project_decision.decision_version, (scope,)

    async def subscribe(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        scope: ScopeKey,
    ) -> ScopeSubscription:
        revision, scopes = await self._authorize_subscription(tx, caller, scope)
        offsets: list[ScopeOffset] = []
        for event_scope in scopes:
            row = await self._cursor(tx, event_scope)
            offsets.append(ScopeOffset(event_scope, row.epoch, row.revision))
        return ScopeSubscription(
            subscriber_id=uuid4(),
            scope=scope,
            actor_id=caller.user_id,
            decision_version=revision,
            offsets=tuple(offsets),
            expires_at=datetime.now(UTC) + SUBSCRIPTION_TTL,
        )

    async def poll(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        subscription: ScopeSubscription,
        *,
        limit: int = 64,
    ) -> ScopeBatch:
        if not 1 <= limit <= 128:
            raise InvalidInput("scoped event read limit must be 1-128")
        if caller.user_id != subscription.actor_id:
            raise ScopeAccessRevoked("stream belongs to another verified User")
        revision, current_scopes = await self._authorize_subscription(
            tx, caller, subscription.scope
        )
        if (
            subscription.expires_at <= datetime.now(UTC)
            or revision != subscription.decision_version
            or set(current_scopes) != {offset.scope for offset in subscription.offsets}
        ):
            raise ScopeResumeRequired("permission epoch or subscription changed")
        returned: list[ScopeEvent] = []
        next_offsets: list[ScopeOffset] = []
        for offset in subscription.offsets:
            cursor = await self._cursor(tx, offset.scope)
            if cursor.epoch != offset.epoch or offset.after_sequence > cursor.revision:
                raise ScopeResumeRequired("scope authorization/event epoch changed")
            earliest = await tx.scalar(
                select(func.min(ScopeEventRow.sequence)).where(
                    ScopeEventRow.scope_kind == offset.scope.kind,
                    ScopeEventRow.scope_id == offset.scope.scope_id,
                )
            )
            if cursor.revision > offset.after_sequence and (
                earliest is None or earliest > offset.after_sequence + 1
            ):
                raise ScopeResumeRequired("scope event resume history expired")
            rows = await tx.scalars(
                select(ScopeEventRow)
                .where(
                    ScopeEventRow.scope_kind == offset.scope.kind,
                    ScopeEventRow.scope_id == offset.scope.scope_id,
                    ScopeEventRow.sequence > offset.after_sequence,
                )
                .order_by(ScopeEventRow.sequence)
                .limit(limit)
            )
            last = offset.after_sequence
            for row in rows:
                returned.append(
                    ScopeEvent(
                        event_id=row.event_id,
                        source_outbox_id=row.source_outbox_id,
                        scope=offset.scope,
                        sequence=row.sequence,
                        epoch=row.epoch,
                        event_type=row.event_type,
                        actor_user_id=row.actor_user_id,
                        payload=row.safe_payload,
                        created_at=row.created_at,
                    )
                )
                last = row.sequence
            next_offsets.append(ScopeOffset(offset.scope, cursor.epoch, last))
        # Do not infer cross-scope total ordering; each source cursor advances
        # only as far as the entries returned for that source.
        returned.sort(
            key=lambda item: (
                item.created_at,
                item.scope.kind,
                str(item.scope.scope_id),
                item.sequence,
            )
        )
        rotated = ScopeSubscription(
            subscriber_id=subscription.subscriber_id,
            scope=subscription.scope,
            actor_id=subscription.actor_id,
            decision_version=revision,
            offsets=tuple(next_offsets),
            expires_at=datetime.now(UTC) + SUBSCRIPTION_TTL,
        )
        return ScopeBatch(rotated, tuple(returned), tuple(next_offsets))

    async def ack_trusted_gateway(
        self,
        tx: AsyncSession,
        *,
        proof: ServiceAuthorizationDecision,
        subscription: ScopeSubscription,
        offset: ScopeOffset,
    ) -> int:
        """Private durable Inbox/WS consumer ACK, not a user-manipulable URL.

        A previously consumed Backend-issued service decision is required;
        raw service/user/project headers cannot acknowledge an event.
        """
        if self.validator is None:
            raise AccessDenied("C2 signed Gateway identity is not enabled")
        if (
            proof.audience != "gateway"
            or proof.operation != "project.metadata.read"
            or proof.expires_at <= datetime.now(UTC)
            or proof.actor_id != subscription.actor_id
            or subscription.scope.kind != "project"
            or subscription.scope.scope_id != proof.project_id
            or subscription.decision_version != proof.decision_version
            or offset.scope not in {candidate.scope for candidate in subscription.offsets}
        ):
            raise AccessDenied("Gateway ACK does not match verified Project scope")
        delivered_offset = next(
            candidate for candidate in subscription.offsets if candidate.scope == offset.scope
        )
        if (
            delivered_offset.epoch != offset.epoch
            or offset.after_sequence > delivered_offset.after_sequence
        ):
            raise ScopeResumeRequired("Gateway cannot ACK events beyond delivered cursor")
        await self.validator.verify_live_decision(tx, proof)
        cursor = await self._cursor(tx, offset.scope)
        if (
            cursor.epoch != offset.epoch
            or offset.after_sequence > cursor.revision
            or offset.after_sequence < 0
        ):
            raise ScopeResumeRequired("scoped Gateway ACK epoch/revision changed")
        await tx.execute(
            insert(ScopeDeliveryReceiptRow)
            .values(
                id=uuid4(),
                subscriber_id=proof.service_id,
                scope_kind=offset.scope.kind,
                scope_id=offset.scope.scope_id,
                epoch=offset.epoch,
                ack_sequence=offset.after_sequence,
            )
            .on_conflict_do_nothing(constraint="uq_scope_subscriber_cursor")
        )
        receipt = await tx.scalar(
            select(ScopeDeliveryReceiptRow)
            .where(
                ScopeDeliveryReceiptRow.subscriber_id == proof.service_id,
                ScopeDeliveryReceiptRow.scope_kind == offset.scope.kind,
                ScopeDeliveryReceiptRow.scope_id == offset.scope.scope_id,
            )
            .with_for_update()
        )
        if receipt is None:
            raise RuntimeError("scope delivery receipt missing after owner insert")
        if receipt.epoch != offset.epoch:
            receipt.epoch = offset.epoch
            receipt.ack_sequence = offset.after_sequence
        else:
            receipt.ack_sequence = max(receipt.ack_sequence, offset.after_sequence)
        receipt.updated_at = datetime.now(UTC)
        return receipt.ack_sequence

    async def prune_expired(self, tx: AsyncSession, *, limit: int = 256) -> int:
        """Retention sweep; never deletes SecurityAudit/Outbox authority."""
        from sqlalchemy import delete

        if not 1 <= limit <= 1000:
            raise InvalidInput("scope retention batch must be 1-1000")
        ids = list(
            await tx.scalars(
                select(ScopeEventRow.event_id)
                .where(ScopeEventRow.expires_at < datetime.now(UTC))
                .order_by(ScopeEventRow.expires_at, ScopeEventRow.event_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        if ids:
            await tx.execute(delete(ScopeEventRow).where(ScopeEventRow.event_id.in_(ids)))
        return len(ids)


class ScopedOutboxSink(DurableOutboxPublisher):
    """Durable local SQL fanout sink for existing OutboxDispatcher.

    This ACK means events are durably stored in scope_events, NOT that
    a remote WebSocket user received them. Source retention is independent.
    """

    def __init__(self, database: PlatformDatabase, feed: ScopedEventFeed) -> None:
        self.database = database
        self.feed = feed

    async def publish(self, event: ClaimedEvent) -> bool:
        async with self.database.transaction() as tx:
            source = await tx.scalar(select(OutboxRow).where(OutboxRow.id == event.event_id))
            if (
                source is None
                or source.event_name != event.event_name
                or outbox_content_sha256(source.event_payload) != event.content_sha256
            ):
                raise InvalidInput("durable scope event source mismatch")
            await self.feed.ingest_outbox(tx, event.event_id)
        return True
