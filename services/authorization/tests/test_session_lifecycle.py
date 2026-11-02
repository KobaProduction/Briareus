"""Lifecycle regressions at the domain/application authority boundary."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from authorization.application.access_commands import (
    AccessCommandScope,
    AccessSessionCommands,
    ApprovalReference,
    ResolveElevation,
    StoredApproval,
)
from authorization.application.sessions import SessionAudit, SessionLifecycle
from authorization.domain.access_commands import VerifiedAccessCommandActor
from authorization.domain.sessions import (
    ElevationRequest,
    SessionAccessDenied,
    SessionConflict,
    SessionResourceGrant,
    SessionState,
    normal_session,
)


def session_state() -> SessionState:
    return normal_session(
        session_uuid=uuid4(),
        project_uuid=uuid4(),
        actor_uuid=uuid4(),
        elevation_policy="requestable",
        label="Work",
        now=datetime.now(UTC),
    )


def approval_for(state: SessionState) -> ElevationRequest:
    return ElevationRequest(
        request_uuid=uuid4(),
        session_uuid=state.session_uuid,
        project_uuid=state.project_uuid,
        requested_by_user_uuid=state.created_by_principal_uuid,
        grants=("files.write",),
        resources=(),
        requested_expires_at=datetime.now(UTC) + timedelta(minutes=4),
    )


class LegacyRepository:
    def __init__(self, state: SessionState) -> None:
        self.state = state
        self.request = approval_for(state)
        self.events: list[SessionAudit] = []
        self.inserted: list[SessionState] = []

    async def session(self, session_uuid: UUID, *, lock: bool = False) -> SessionState:
        assert session_uuid == self.state.session_uuid
        _ = lock
        return self.state

    async def add_session(self, state: SessionState) -> None:
        self.inserted.append(state)

    async def save_session(self, state: SessionState) -> None:
        self.state = state

    async def approval(self, request_uuid: UUID) -> ElevationRequest:
        assert request_uuid == self.request.request_uuid
        return self.request

    async def add_approval(self, request: ElevationRequest) -> None:
        self.request = request

    async def save_approval(self, request: ElevationRequest) -> None:
        self.request = request

    def audit(self, event: SessionAudit) -> None:
        self.events.append(event)


class Authority:
    async def require_access(self, *, for_write: bool, approve: bool = False) -> None:
        _ = for_write, approve


class ResourceScopes:
    def requested(self, grants: tuple[str, ...]) -> tuple[SessionResourceGrant, ...]:
        _ = grants
        return ()

    def approved(
        self, request: ElevationRequest, grants: tuple[str, ...]
    ) -> tuple[SessionResourceGrant, ...]:
        _ = request, grants
        raise SessionAccessDenied("stored resource approval scope invalid")


def legacy_service(repository: LegacyRepository) -> SessionLifecycle:
    return SessionLifecycle(
        repository=repository,
        authority=Authority(),
        resources=ResourceScopes(),
        actor_uuid=uuid4(),
        project_uuid=repository.state.project_uuid,
    )


class LiveRepository:
    def __init__(self, base: SessionState) -> None:
        self.states = {base.session_uuid: base}
        self.request = approval_for(base)
        self.calls: list[str] = []
        self.child_uuids: tuple[UUID, ...] = ()
        self.owner_checked = False

    async def session(self, session_uuid: UUID) -> SessionState | None:
        self.calls.append("session")
        return self.states.get(session_uuid)

    async def approval_reference(self, approval_uuid: UUID) -> ApprovalReference:
        assert approval_uuid == self.request.request_uuid
        self.calls.append("reference")
        return ApprovalReference(self.request.project_uuid, self.request.session_uuid)

    async def approval(self, approval_uuid: UUID) -> StoredApproval:
        assert approval_uuid == self.request.request_uuid
        self.calls.append("approval")
        return StoredApproval(self.request, True)

    def add_session(self, state: SessionState) -> None:
        self.states[state.session_uuid] = state

    def save_session(self, state: SessionState) -> None:
        self.states[state.session_uuid] = state

    def add_approval(self, request: ElevationRequest) -> None:
        self.request = request

    def save_approval(self, request: ElevationRequest) -> None:
        self.request = request

    def approval_resources(self, request: ElevationRequest) -> tuple[SessionResourceGrant, ...]:
        assert request.request_uuid == self.request.request_uuid
        return (
            SessionResourceGrant("files", "write_file", "files.write", "workspace_path", "owned"),
        )

    def require_current_owner(self, resources: tuple[SessionResourceGrant, ...]) -> None:
        assert resources
        self.owner_checked = True

    async def children(self, parent: SessionState) -> tuple[UUID, ...]:
        assert parent.session_uuid == self.request.session_uuid
        self.calls.append("children")
        return self.child_uuids

    def audit(self, action: str, target_uuid: UUID) -> None:
        _ = target_uuid
        self.calls.append(action)


def live_service(
    repository: LiveRepository, action: str = "session.resolve_elevation"
) -> AccessSessionCommands:
    actor = VerifiedAccessCommandActor(
        uuid4(),
        repository.request.project_uuid,
        uuid4(),
        "session.resolve_elevation",
        True,
        True,
        "rauthy",
        "briareus:access",
        datetime.now(UTC) + timedelta(seconds=20),
    )
    if action == "session.revoke":
        actor = replace(actor, action="session.revoke")
    return AccessSessionCommands(
        repository,
        actor,
        AccessCommandScope(
            actor.project_uuid,
            actor.operation_uuid,
            action,
            True,
        ),
    )


class SessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_does_not_decode_malformed_legacy_resource_scope(self) -> None:
        repository = LegacyRepository(session_state())
        result = await legacy_service(repository).resolve_elevation(
            repository.request.request_uuid,
            approve=False,
            allowed_grants=None,
            expected_version=1,
        )
        self.assertIsNone(result)
        self.assertEqual(repository.request.status, "rejected")
        self.assertEqual(repository.request.version, 2)

    async def test_legacy_expired_base_conflicts_even_when_rejecting(self) -> None:
        repository = LegacyRepository(replace(session_state(), hard_expires_at=datetime.now(UTC)))
        with self.assertRaisesRegex(SessionConflict, "base AgentSession expired"):
            await legacy_service(repository).resolve_elevation(
                repository.request.request_uuid,
                approve=False,
                allowed_grants=None,
                expected_version=1,
            )
        self.assertEqual(repository.events, [])

    async def test_legacy_repeated_revoke_emits_once(self) -> None:
        repository = LegacyRepository(session_state())
        service = legacy_service(repository)
        first = await service.revoke(repository.state.session_uuid)
        second = await service.revoke(repository.state.session_uuid)
        self.assertEqual(first, second)
        self.assertEqual([event.action for event in repository.events], ["session.revoked"])
        self.assertEqual(second.version, 2)

    async def test_legacy_stale_grant_revision_has_no_side_effect(self) -> None:
        repository = LegacyRepository(session_state())
        with self.assertRaises(SessionConflict):
            await legacy_service(repository).request_elevation(
                repository.state.session_uuid,
                ("files.write",),
                seconds=30,
                expected_grant_revision=2,
            )
        self.assertEqual(repository.events, [])

    async def test_live_resolution_locks_base_before_approval_and_caps_child_lifetime(self) -> None:
        base = replace(session_state(), hard_expires_at=datetime.now(UTC) + timedelta(seconds=40))
        repository = LiveRepository(base)
        result = await live_service(repository).resolve_elevation(
            ResolveElevation(
                repository.request.request_uuid,
                1,
                True,
                None,
            )
        )
        self.assertEqual(repository.calls[:3], ["reference", "session", "approval"])
        self.assertTrue(repository.owner_checked)
        self.assertIsNotNone(result.issued_session_uuid)
        child = (
            repository.states[result.issued_session_uuid]
            if result.issued_session_uuid is not None
            else None
        )
        self.assertIsNotNone(child)
        if child is not None:
            self.assertEqual(child.hard_expires_at, base.hard_expires_at)

    async def test_live_self_rejection_is_denied(self) -> None:
        repository = LiveRepository(session_state())
        service = live_service(repository)
        service.actor = replace(service.actor, actor_uuid=repository.request.requested_by_user_uuid)
        with self.assertRaisesRegex(SessionAccessDenied, "cannot resolve own"):
            await service.resolve_elevation(
                ResolveElevation(repository.request.request_uuid, 1, False, None)
            )
        self.assertEqual(repository.request.status, "pending")

    async def test_live_transitive_revoke_is_atomic_and_audits_child_first(self) -> None:
        base = session_state()
        child = replace(base, session_uuid=uuid4(), is_elevated=True, elevation_policy="fixed")
        repository = LiveRepository(base)
        repository.states[child.session_uuid] = child
        repository.child_uuids = (child.session_uuid,)
        result = await live_service(repository, "session.revoke").revoke_session(
            base.session_uuid, 1
        )
        self.assertEqual(result.status, "revoked")
        self.assertEqual(repository.states[child.session_uuid].status, "revoked")
        self.assertEqual(repository.calls[-2:], ["session.revoked_by_parent", "session.revoked"])

    async def test_live_expired_authority_cannot_mutate_locked_session(self) -> None:
        repository = LiveRepository(session_state())
        service = live_service(repository, "session.revoke")
        service.actor = replace(service.actor, expires_at=datetime.now(UTC))
        with self.assertRaises(SessionAccessDenied):
            await service.revoke_session(repository.request.session_uuid, 1)
        self.assertEqual(repository.states[repository.request.session_uuid].status, "active")
        self.assertEqual(repository.calls, ["session"])


if __name__ == "__main__":
    unittest.main()
