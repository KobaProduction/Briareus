"""Map persisted session records without loading legacy platform composition."""

from uuid import UUID

from authorization._session_persistence import ProjectAgentSessionRow
from authorization.domain.sessions import SessionState


def stored_operations(operations: tuple[str, ...] | None) -> tuple[str, ...]:
    return operations or ()


def session_state(row: ProjectAgentSessionRow) -> SessionState:
    return SessionState(
        session_uuid=row.session_uuid,
        project_uuid=row.project_id,
        created_by_principal_uuid=row.created_by_principal_id,
        grants=stored_operations(row.grants.operations),
        is_elevated=row.is_elevated,
        hard_expires_at=row.hard_expires_at,
        status=row.status,
        version=row.version,
        label=row.label,
        elevation_policy=row.elevation_policy,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


class _SessionStateWriter:
    _sessions: dict[UUID, ProjectAgentSessionRow]

    def _store_session_state(self, state: SessionState) -> None:
        row = self._sessions[state.session_uuid]
        row.status = state.status
        row.revoked_at = state.revoked_at
        row.version = state.version
