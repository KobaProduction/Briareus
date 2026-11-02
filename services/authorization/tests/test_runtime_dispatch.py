from __future__ import annotations

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from authorization.application.access_inputs import ApprovalListCommand, SessionGetCommand
from authorization.application.event_receipts import EventPageResponse as RuntimeEvents
from authorization.application.runtime_dispatch import (
    DispatchRuntime,
    RuntimeAction,
    RuntimeApprovals,
    RuntimePermit,
    RuntimeRequest,
    RuntimeSessions,
    RuntimeWriteReceipt,
)
from authorization.application.runtime_effects import (
    RuntimeEffectCall,
    RuntimeEffectConfig,
    RuntimeEffectPreparation,
    RuntimeGrant,
    RuntimeGrantTransaction,
)
from authorization.application.runtime_inputs import (
    RuntimeEventQuery,
    RuntimeResourceQuery,
    RuntimeWriteCommand,
)
from authorization.application.session_receipts import RevokeSessionResponse
from authorization.domain.runtime_policy import (
    RuntimeAccessDenied,
    RuntimeActor,
    RuntimeIdentity,
    RuntimeIdentityRequired,
    RuntimePlacement,
)
from runtime_peer.runtime_resource_receipts import RuntimeResources


class DispatchPorts:
    def __init__(self, actor: RuntimeActor) -> None:
        self.actor = actor
        self.calls: list[str] = []
        self.session_requests: list[tuple[RuntimeActor, ApprovalListCommand]] = []

    async def resolve(self, identity: RuntimeIdentity) -> RuntimeActor:
        del identity
        self.calls.append("actor")
        return self.actor

    async def sessions(
        self,
        actor: RuntimeActor,
        command: ApprovalListCommand,
        *,
        detail: bool,
    ) -> RuntimeSessions:
        self.calls.append("sessions")
        self.session_requests.append((actor, command))
        return RuntimeSessions((), detail)

    async def approvals(
        self, actor: RuntimeActor, command: ApprovalListCommand
    ) -> RuntimeApprovals:
        del actor, command
        self.calls.append("approvals")
        return RuntimeApprovals(())

    async def events(self, actor: RuntimeActor, command: RuntimeEventQuery) -> RuntimeEvents:
        del actor, command
        self.calls.append("events")
        return RuntimeEvents(items=(), truncated=False, next=None)

    async def catalogue(
        self, actor: RuntimeActor, command: RuntimeResourceQuery
    ) -> RuntimeResources:
        del command
        self.calls.append("catalogue")
        return RuntimeResources(items=(), expires_at=actor.expires_at.isoformat())

    async def prepare(
        self, actor: RuntimeActor, hand: str, command: RuntimeEffectCall
    ) -> RuntimePermit:
        del actor, hand, command
        self.calls.append("prepare")
        return RuntimePermit("test-only-permit")

    async def execute(
        self,
        actor: RuntimeActor,
        action: RuntimeAction,
        command: RuntimeWriteCommand,
    ) -> RuntimeWriteReceipt:
        del action, command
        self.calls.append("write")
        return RuntimeWriteReceipt(
            200,
            RevokeSessionResponse(
                session_uuid=str(uuid4()),
                project_uuid=str(actor.project_uuid),
                status="revoked",
                revision=2,
            ),
        )


class DispatchRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime.now(UTC)
        self.actor = RuntimeActor(
            "https://issuer.example/",
            "subject",
            uuid4(),
            uuid4(),
            self.now + timedelta(seconds=20),
            ("use_resources",),
            "user",
        )
        self.identity = RuntimeIdentity(
            self.actor.issuer,
            self.actor.subject,
            self.actor.actor_uuid,
            self.actor.project_uuid,
            self.now + timedelta(seconds=10),
        )
        self.ports = DispatchPorts(self.actor)
        self.dispatch = DispatchRuntime(self.ports, self.ports, self.ports, self.ports, self._clock)
        self.list_command = ApprovalListCommand(project_uuid=self.actor.project_uuid, limit=50)

    def _clock(self) -> datetime:
        return self.now

    async def test_independent_subject_binding_is_required_before_routing(self) -> None:
        self.ports.actor = replace(self.actor, subject="another-subject")
        with self.assertRaises(RuntimeAccessDenied):
            await self.dispatch.execute(
                RuntimeRequest(self.identity, "session.list", self.list_command)
            )
        self.assertEqual(self.ports.calls, ["actor"])

    async def test_expired_identity_stops_before_platform(self) -> None:
        identity = replace(self.identity, expires_at=self.now)
        with self.assertRaises(RuntimeIdentityRequired):
            await self.dispatch.execute(RuntimeRequest(identity, "session.list", self.list_command))
        self.assertEqual(self.ports.calls, [])

    async def test_actor_proof_is_clamped_to_bff_identity_expiry(self) -> None:
        await self.dispatch.execute(
            RuntimeRequest(self.identity, "session.list", self.list_command)
        )
        self.assertEqual(
            self.ports.session_requests[-1],
            (
                replace(self.actor, expires_at=self.identity.expires_at),
                self.list_command,
            ),
        )

    async def test_resource_permission_is_required_before_effect_preparation(self) -> None:
        self.ports.actor = replace(self.actor, permissions=())
        with self.assertRaises(RuntimeAccessDenied):
            await self.dispatch.execute(
                RuntimeRequest(
                    self.identity,
                    "terminal.prepare",
                    RuntimeEffectCall("terminal_exec", "a" * 64, uuid4(), 1, uuid4()),
                )
            )
        self.assertEqual(self.ports.calls, ["actor"])

    async def test_session_detail_and_events_keep_distinct_scenarios(self) -> None:
        detail = await self.dispatch.execute(
            RuntimeRequest(
                self.identity,
                "session.get",
                SessionGetCommand(project_uuid=self.actor.project_uuid, session_uuid=uuid4()),
            )
        )
        events = await self.dispatch.execute(
            RuntimeRequest(
                self.identity,
                "events.read",
                RuntimeEventQuery(
                    since=(self.now - timedelta(seconds=1)).isoformat(), until=self.now.isoformat()
                ),
            )
        )
        self.assertIsInstance(detail, RuntimeSessions)
        if isinstance(detail, RuntimeSessions):
            self.assertTrue(detail.detail)
        self.assertIsInstance(events, RuntimeEvents)


class EffectPorts:
    def __init__(self, actor: RuntimeActor, now: datetime) -> None:
        self.now = now
        self.placement = RuntimePlacement(
            "terminal",
            actor.project_uuid,
            True,
            f"project-terminal:{actor.project_uuid}:{7:064x}",
            7,
            ("terminal_exec",),
        )
        self.session_expiry = now + timedelta(seconds=3)
        self.expire_during_lock = False
        self.trace: list[str] = []
        self.signed: list[
            tuple[RuntimeActor, RuntimePlacement, RuntimeEffectCall, RuntimeEffectConfig, int, int]
        ] = []

    @property
    def configured(self) -> bool:
        return True

    def clock(self) -> datetime:
        return self.now

    async def inspect(self, actor: RuntimeActor, hand: str) -> RuntimePlacement:
        self.trace.append(f"inspect:{actor.project_uuid}:{hand}")
        return self.placement

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[RuntimeGrantTransaction]:
        self.trace.append("transaction")
        try:
            yield self
        finally:
            self.trace.append("closed")

    async def require_grant(
        self,
        actor: RuntimeActor,
        placement: RuntimePlacement,
        call: RuntimeEffectCall,
        config: RuntimeEffectConfig,
    ) -> RuntimeGrant:
        self.trace.append(f"grant:{placement.resource_id}:{call.tool}:{config.action}")
        if self.expire_during_lock:
            self.now = actor.expires_at + timedelta(seconds=1)
        return RuntimeGrant(self.session_expiry)

    def sign(
        self,
        actor: RuntimeActor,
        placement: RuntimePlacement,
        call: RuntimeEffectCall,
        config: RuntimeEffectConfig,
        *,
        issued_at: int,
        expires_at: int,
    ) -> str:
        self.trace.append("sign")
        self.signed.append((actor, placement, call, config, issued_at, expires_at))
        return "test-only-permit"


class RuntimeEffectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        self.actor = RuntimeActor(
            "https://issuer.example/",
            "subject",
            uuid4(),
            uuid4(),
            now + timedelta(seconds=20),
            ("use_resources",),
            "user",
        )
        self.ports = EffectPorts(self.actor, now)
        self.preparation = RuntimeEffectPreparation(
            self.ports, self.ports, self.ports, self.ports.clock
        )
        self.command = RuntimeEffectCall("terminal_exec", "a" * 64, uuid4(), 7, uuid4())

    async def test_session_ttl_bounds_signed_lease(self) -> None:
        result = await self.preparation.prepare(self.actor, "terminal", self.command)
        self.assertEqual(result.permit, "test-only-permit")
        self.assertEqual(len(self.ports.signed), 1)
        signed = self.ports.signed[0]
        self.assertEqual(signed[-1], int(self.ports.session_expiry.timestamp()))
        self.assertEqual(signed[3].audience, "briareus:terminal-worker")
        self.assertEqual(signed[2].expected_grant_revision, 7)
        self.assertEqual(self.ports.trace[-2:], ["sign", "closed"])

    async def test_expiration_while_waiting_for_grant_lock_prevents_signing(self) -> None:
        self.ports.expire_during_lock = True
        with self.assertRaises(RuntimeAccessDenied):
            await self.preparation.prepare(self.actor, "terminal", self.command)
        self.assertEqual(self.ports.signed, [])
        self.assertEqual(self.ports.trace[-1], "closed")

    async def test_unbound_physical_placement_stops_before_grant_read(self) -> None:
        self.ports.placement = replace(self.ports.placement, resource_id="another-workspace")
        with self.assertRaises(RuntimeAccessDenied):
            await self.preparation.prepare(self.actor, "terminal", self.command)
        self.assertNotIn("transaction", self.ports.trace)
        self.assertEqual(self.ports.signed, [])

    async def test_actor_ttl_and_maximum_lease_are_both_enforced(self) -> None:
        self.ports.session_expiry = self.ports.now + timedelta(seconds=300)
        await self.preparation.prepare(self.actor, "terminal", self.command)
        self.assertEqual(self.ports.signed[-1][-1], int(self.ports.now.timestamp()) + 5)
        actor = replace(self.actor, expires_at=self.ports.now + timedelta(seconds=2))
        await self.preparation.prepare(actor, "terminal", self.command)
        self.assertEqual(self.ports.signed[-1][-1], int(actor.expires_at.timestamp()))


if __name__ == "__main__":
    unittest.main()
