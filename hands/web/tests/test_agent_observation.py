"""Passive frame attribution and invalidation without execution or lease ports."""

import asyncio
import base64
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult

from node_protocol.effect import HumanEffectPermit, NodeEffectPermit
from web_hand.domain.agent_observation import (
    AgentBrowserFrame,
    AgentBrowserObservations,
    AgentBrowserOwner,
)
from web_hand.infrastructure.agent_observation import capture_agent_preview
from web_hand.infrastructure.browser_ipc import BrowserReply
from web_hand.node_supervisor import WebSupervisor

PNG = b"\x89PNG\r\n\x1a\nframe"


def agent_permit() -> NodeEffectPermit:
    return NodeEffectPermit(
        module="web",
        node_uuid=uuid4(),
        placement_uuid=uuid4(),
        project_uuid=uuid4(),
        workspace_uuid=uuid4(),
        actor_uuid=uuid4(),
        request_uuid=uuid4(),
        agent_session_uuid=uuid4(),
        grant_revision=1,
        fingerprint="a" * 64,
        body_digest="b" * 64,
        bearer_digest="c" * 64,
        arguments_digest="d" * 64,
        method="tools/call",
        tool="web_operation_start",
        resource_id="browser:" + "x" * 80,
        issued_at=100,
        expires_at=105,
    )


def preview_reply() -> BrowserReply:
    return BrowserReply(
        result=CallToolResult(
            content=[],
            structured_content={
                "page_id": "page-one",
                "url": "https://example.com",
                "title": "Example",
                "mime_type": "image/png",
                "data_base64": base64.b64encode(PNG).decode(),
            },
        )
    )


class AgentObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = AgentBrowserObservations()
        self.permit = agent_permit()
        self.owner = AgentBrowserOwner(
            self.permit.project_uuid,
            self.permit.placement_uuid,
            self.permit.actor_uuid,
            self.permit.agent_session_uuid,
            self.permit.grant_revision,
        )

    def capture(self) -> None:
        capture_agent_preview(
            self.cache,
            self.cache.generation,
            self.permit,
            "local_browser_preview",
            preview_reply(),
        )

    def test_frame_is_attributed_to_verified_permit_and_is_immutable(self) -> None:
        self.capture()
        frame = self.cache.read(self.owner)
        self.assertIsNotNone(frame)
        if frame is None:
            self.fail("Confirmed preview missing")
        self.assertEqual(frame.png, PNG)
        self.assertEqual(frame.request_uuid, self.permit.request_uuid)
        self.assertGreater(frame.captured_at, 0)
        for owner in (
            replace(self.owner, project_uuid=uuid4()),
            replace(self.owner, placement_uuid=uuid4()),
            replace(self.owner, actor_uuid=uuid4()),
            replace(self.owner, agent_session_uuid=uuid4()),
            replace(self.owner, grant_revision=2),
        ):
            self.assertIsNone(self.cache.read(owner))

    def test_runtime_replacement_discards_frame_and_late_reply(self) -> None:
        self.capture()
        generation = self.cache.generation
        self.cache.clear()
        capture_agent_preview(
            self.cache,
            generation,
            self.permit,
            "local_browser_preview",
            preview_reply(),
        )
        self.assertIsNone(self.cache.read(self.owner))

    def test_human_preview_does_not_enter_agent_cache(self) -> None:
        human = HumanEffectPermit.model_validate(
            {
                **self.permit.model_dump(exclude={"agent_session_uuid", "grant_revision"}),
                "human": True,
                "resource_revision": 1,
            }
        )
        capture_agent_preview(
            self.cache,
            self.cache.generation,
            human,
            "local_browser_preview",
            preview_reply(),
        )
        self.assertIsNone(self.cache.read(self.owner))

    def test_error_and_other_tool_replies_are_not_observations(self) -> None:
        capture_agent_preview(
            self.cache,
            0,
            self.permit,
            "local_browser_open",
            preview_reply(),
        )
        failed = preview_reply()
        if failed.result is not None:
            failed.result.is_error = True
        capture_agent_preview(self.cache, 0, self.permit, "local_browser_preview", failed)
        self.assertIsNone(self.cache.read(self.owner))

    def test_malformed_and_oversized_image_never_replace_previous_frame(self) -> None:
        self.capture()
        first = self.cache.read(self.owner)
        for data in ("invalid base64", base64.b64encode(b"not png").decode(), "A" * 1_000_001):
            reply = preview_reply()
            if reply.result is not None and reply.result.structured_content is not None:
                reply.result.structured_content["data_base64"] = data
            capture_agent_preview(self.cache, 0, self.permit, "local_browser_preview", reply)
            self.assertIs(self.cache.read(self.owner), first)

    def test_read_is_passive_and_clear_is_terminal_for_generation(self) -> None:
        self.capture()
        first = self.cache.read(self.owner)
        for _ in range(3):
            self.assertIs(self.cache.read(self.owner), first)
        self.assertEqual(self.cache.generation, 0)
        with self.assertRaises(ValueError):
            AgentBrowserFrame(self.owner, uuid4(), 1, "page", "", "", PNG + b"x" * 750_000)


class SupervisorObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_journal_replay_neither_recaptures_nor_resurrects_old_frame(self) -> None:
        permit = agent_permit().model_copy(update={"expires_at": int(time.time()) + 4})
        reply = preview_reply().model_copy(update={"id": permit.request_uuid})
        child = Mock(spec=asyncio.subprocess.Process)
        child.stdin = Mock()
        child.stdin.drain = AsyncMock()
        child.stdout = Mock()
        child.stdout.readline = AsyncMock(return_value=reply.model_dump_json().encode() + b"\n")
        runtime = WebSupervisor.__new__(WebSupervisor)
        runtime.child = child
        runtime.profile = Path("/browser/profile")
        runtime.observations = AgentBrowserObservations()
        owner = AgentBrowserOwner(
            permit.project_uuid,
            permit.placement_uuid,
            permit.actor_uuid,
            permit.agent_session_uuid,
            permit.grant_revision,
        )
        command = CallToolRequestParams(
            name="local_browser_preview", arguments={"page_id": "page-one"}
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "stop", AsyncMock()):
            runtime.state = Path(directory)
            await runtime.exchange(command, permit)
            frame = runtime.observations.read(owner)
            self.assertIsNotNone(frame)
            await runtime.exchange(command, permit)
            self.assertIs(runtime.observations.read(owner), frame)
            runtime.observations.clear()
            await runtime.exchange(command, permit)
            self.assertIsNone(runtime.observations.read(owner))
        child.stdout.readline.assert_awaited_once()
        child.stdin.write.assert_called_once()
