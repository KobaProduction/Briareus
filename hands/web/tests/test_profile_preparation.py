"""Session replacement prepares metadata without consuming native effect authority."""

import asyncio
import unittest
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

from web_hand.application.prepare_profile import PrepareProfile, ProfileReadiness
from web_hand.domain.profile import LeaseIdentity, ProfileObservation
from web_hand.node_supervisor import WebSupervisor


@dataclass
class ProfileFixture:
    observation: ProfileObservation
    steps: list[str] = field(default_factory=list)

    def profile_observation(self) -> ProfileObservation:
        return self.observation

    def bind_warm_profile(self, profile_key: str) -> None:
        self.steps.append("bind:" + profile_key)

    def prepare_profile(self, profile_key: str) -> None:
        self.steps.append("prepare:" + profile_key)


class ProfilePreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.identity: LeaseIdentity = ("actor", "session", 1)

    async def test_unbound_warm_metadata_binds_without_restarting(self) -> None:
        runtime = ProfileFixture(ProfileObservation(None, None, True, True))
        readiness = await PrepareProfile(runtime).execute("profile", self.identity)
        self.assertIs(readiness, ProfileReadiness.READY)
        self.assertEqual(runtime.steps, ["bind:profile"])

    async def test_each_foreign_session_or_revision_queues_preparation(self) -> None:
        for identity in (("other", "session", 1), ("actor", "other", 1), ("actor", "session", 2)):
            with self.subTest(identity=identity):
                runtime = ProfileFixture(ProfileObservation("profile", identity, True, True))
                readiness = await PrepareProfile(runtime).execute("profile", self.identity)
                self.assertIs(readiness, ProfileReadiness.SESSION_PREPARING)
                self.assertEqual(runtime.steps, ["prepare:profile"])

    async def test_a_different_profile_queues_replacement(self) -> None:
        runtime = ProfileFixture(ProfileObservation("old", self.identity, True, True))
        await PrepareProfile(runtime).execute("profile", self.identity)
        self.assertEqual(runtime.steps, ["prepare:profile"])

    async def test_running_child_with_unprepared_metadata_cannot_receive_authority(self) -> None:
        runtime = ProfileFixture(ProfileObservation("profile", None, False, True))
        readiness = await PrepareProfile(runtime).execute("profile", self.identity)
        self.assertIs(readiness, ProfileReadiness.METADATA_PREPARING)
        self.assertEqual(runtime.steps, ["prepare:profile"])

    async def test_background_replacement_marks_unready_and_stops_before_start(self) -> None:
        supervisor = WebSupervisor.__new__(WebSupervisor)
        supervisor.child_ready = True
        supervisor.lock = asyncio.Lock()
        steps: list[str] = []

        async def stop() -> None:
            steps.append("stop")

        async def start(profile: str | None) -> None:
            steps.append("start:" + str(profile))

        with (
            patch.object(supervisor, "warming_task", None, create=True),
            patch.object(supervisor, "stop", AsyncMock(side_effect=stop)),
            patch.object(supervisor, "start", AsyncMock(side_effect=start)),
        ):
            supervisor.prepare_profile("new")
            self.assertFalse(supervisor.child_ready)
            task = supervisor.warming_task
            assert task is not None
            await task
        self.assertEqual(steps, ["stop", "start:new"])

    async def test_missing_child_rebuilds_metadata_without_claiming_runtime_ready(self) -> None:
        runtime = ProfileFixture(ProfileObservation("profile", self.identity, False, False))
        readiness = await PrepareProfile(runtime).execute("profile", self.identity)
        self.assertIs(readiness, ProfileReadiness.METADATA_PREPARING)
        self.assertEqual(runtime.steps, ["prepare:profile"])

    async def test_existing_child_does_not_restart_or_renew_a_lease(self) -> None:
        runtime = ProfileFixture(ProfileObservation("profile", self.identity, True, True))
        readiness = await PrepareProfile(runtime).execute("profile", self.identity)
        self.assertIs(readiness, ProfileReadiness.READY)
        self.assertEqual(runtime.steps, [])
