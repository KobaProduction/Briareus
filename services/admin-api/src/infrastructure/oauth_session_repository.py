from __future__ import annotations

import hashlib
from collections.abc import Sequence

from domain.oauth_sessions import OAuthSession, OAuthSessionObservation
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.oauth_session_contracts import OAuthSessionEvent

from ._adapter_resources import _SqlAlchemyRepository
from .database import OAuthSessionRecord
from .oauth_session_codec import decode_observed_scopes, encode_observed_scopes


class SqlAlchemyOAuthSessionRepository(_SqlAlchemyRepository):
    @staticmethod
    def _domain(record: OAuthSessionRecord) -> OAuthSession:
        return OAuthSession(
            id=record.id,
            client_id=record.client_id,
            client_name=record.client_name,
            resource=record.resource,
            login=record.login,
            subject=record.subject,
            scopes=decode_observed_scopes(record.scopes_json),
            status=record.status,
            last_event=record.last_event,
            access_jti=record.access_jti,
            refresh_jti=record.refresh_jti,
            previous_refresh_jti=record.previous_refresh_jti,
            access_expires_at=record.access_expires_at,
            refresh_expires_at=record.refresh_expires_at,
            last_used_at=record.last_used_at,
            last_refresh_at=record.last_refresh_at,
            revoked_at=record.revoked_at,
            error_type=record.error_type,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def _resolve_record(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        refresh_jti: str,
        access_jti: str,
        client_id: str,
        resource: str,
        login: str,
    ) -> OAuthSessionRecord | None:
        if session_id:
            record = await session.get(OAuthSessionRecord, session_id)
            if record is not None:
                return record
        if refresh_jti or access_jti:
            criteria = []
            if refresh_jti:
                criteria.extend(
                    [
                        OAuthSessionRecord.refresh_jti == refresh_jti,
                        OAuthSessionRecord.previous_refresh_jti == refresh_jti,
                    ]
                )
            if access_jti:
                criteria.append(OAuthSessionRecord.access_jti == access_jti)
            record = (
                await session.scalars(select(OAuthSessionRecord).where(or_(*criteria)))
            ).first()
            if record is not None:
                return record
        if client_id and resource:
            stmt = select(OAuthSessionRecord).where(
                OAuthSessionRecord.client_id == client_id,
                OAuthSessionRecord.resource == resource,
            )
            if login:
                stmt = stmt.where(OAuthSessionRecord.login == login)
            return (
                await session.scalars(stmt.order_by(OAuthSessionRecord.updated_at.desc()))
            ).first()
        return None

    @staticmethod
    def _new_session(value: OAuthSessionEvent) -> OAuthSession:
        identity = "\0".join((value.client_id, value.resource, value.login))
        identity_id = (
            "observed-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
            if value.client_id and value.resource
            else ""
        )
        identifier = (
            value.session_id or identity_id or f"orphan-{value.refresh_jti or value.access_jti}"
        )
        if not identifier or identifier == "orphan-":
            raise ValueError("oauth session event has no stable identifier")
        return OAuthSession(
            id=identifier[:128], client_id=value.client_id, created_at=value.occurred_at
        )

    @staticmethod
    def _observation(value: OAuthSessionEvent) -> OAuthSessionObservation:
        return OAuthSessionObservation(
            client_id=value.client_id,
            client_name=value.client_name,
            resource=value.resource,
            login=value.login,
            subject=value.subject,
            scopes=tuple(value.scopes),
            status=value.status,
            event=value.event,
            access_jti=value.access_jti,
            refresh_jti=value.refresh_jti,
            access_expires_at=value.access_expires_at,
            refresh_expires_at=value.refresh_expires_at,
            occurred_at=value.occurred_at,
            error_type=value.error_type,
            error_message=value.error_message,
        )

    @staticmethod
    def _write(record: OAuthSessionRecord, state: OAuthSession, *, write_scopes: bool) -> None:
        record.client_id = state.client_id
        record.client_name = state.client_name
        record.resource = state.resource
        record.login = state.login
        record.subject = state.subject
        if write_scopes:
            record.scopes_json = encode_observed_scopes(state.scopes)
        record.status = state.status
        record.last_event = state.last_event
        record.access_jti = state.access_jti
        record.refresh_jti = state.refresh_jti
        record.previous_refresh_jti = state.previous_refresh_jti
        record.access_expires_at = state.access_expires_at
        record.refresh_expires_at = state.refresh_expires_at
        record.last_used_at = state.last_used_at
        record.last_refresh_at = state.last_refresh_at
        record.revoked_at = state.revoked_at
        record.error_type = state.error_type
        record.error_message = state.error_message
        record.updated_at = state.updated_at

    async def apply_event(self, event: OAuthSessionEvent) -> OAuthSession:
        value = OAuthSessionEvent.model_validate(event)
        async with self.sessions.begin() as session:
            record = await self._resolve_record(
                session,
                session_id=value.session_id,
                refresh_jti=value.refresh_jti,
                access_jti=value.access_jti,
                client_id=value.client_id,
                resource=value.resource,
                login=value.login,
            )
            if record is None:
                state = self._new_session(value)
                record = OAuthSessionRecord(
                    id=state.id, client_id=state.client_id, created_at=state.created_at
                )
                session.add(record)
            else:
                state = self._domain(record)
            state.observe(self._observation(value))
            self._write(record, state, write_scopes=bool(value.scopes))
            await session.flush()
            return self._domain(record)

    async def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]:
        size = max(1, min(limit, 1000))
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(OAuthSessionRecord)
                    .order_by(OAuthSessionRecord.updated_at.desc())
                    .limit(size)
                )
            ).all()
            return [self._domain(row) for row in rows]
