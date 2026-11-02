"""Operator authority and stream transitions retain their effect order."""

import unittest
from typing import cast
from unittest.mock import AsyncMock, Mock

from modules.web.application.operator_session import (
    OperatorBrowser,
    OperatorEvents,
    OperatorSession,
)
from modules.web.domain.operator import OperatorCommand, OperatorOwner, OperatorViolation


class OperatorSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.trace: list[str] = []

        async def select(owner: str, page: str) -> None:
            self.trace.append(f"select:{owner}:{page}")

        async def state(owner: str) -> None:
            self.trace.append(f"state:{owner}")

        async def start(owner: str, page: str) -> None:
            self.trace.append(f"start:{owner}:{page}")

        async def stop() -> None:
            self.trace.append("stop")

        async def clean(owner: str) -> str:
            self.trace.append(f"clean:{owner}")
            return "clean"

        async def release(owner: str) -> None:
            self.trace.append(f"release:{owner}")

        self.browser = Mock(
            acquire=AsyncMock(return_value=OperatorOwner("owner", "initial")),
            select=AsyncMock(side_effect=select),
            selected=AsyncMock(return_value="next"),
            clean_browser=AsyncMock(side_effect=clean),
            release=AsyncMock(side_effect=release),
            page_action=AsyncMock(),
            key=AsyncMock(),
            text=AsyncMock(),
            mouse=AsyncMock(),
            set_access=AsyncMock(),
        )
        self.events = Mock(
            state=AsyncMock(side_effect=state),
            start_stream=AsyncMock(side_effect=start),
            stop_stream=AsyncMock(side_effect=stop),
        )
        self.session = await OperatorSession.acquire(
            cast(OperatorBrowser, self.browser),
            cast(OperatorEvents, self.events),
        )

    async def test_initial_state_selection_clean_and_release_order(self) -> None:
        await self.session.start()
        await self.session.handle(OperatorCommand("select_page", page_id="chosen"))
        await self.session.handle(OperatorCommand("clean_browser"))
        self.assertFalse(await self.session.handle(OperatorCommand("release")))
        await self.session.close()
        self.assertEqual(
            self.trace,
            [
                "state:owner",
                "start:owner:initial",
                "select:owner:chosen",
                "stop",
                "start:owner:chosen",
                "state:owner",
                "stop",
                "clean:owner",
                "start:owner:clean",
                "state:owner",
                "stop",
                "release:owner",
            ],
        )

    async def test_input_cannot_target_an_unselected_page_or_escalate_boolean_access(self) -> None:
        for action in ("key", "text", "mouse"):
            with self.subTest(action=action), self.assertRaises(OperatorViolation):
                await self.session.handle(OperatorCommand(action, page_id="foreign"))
        for action in ("set_page_agent_access", "set_agent_access", "set_developer_access"):
            with self.subTest(action=action), self.assertRaises(OperatorViolation):
                await self.session.handle(OperatorCommand(action))
        self.browser.key.assert_not_awaited()
        self.browser.text.assert_not_awaited()
        self.browser.mouse.assert_not_awaited()
        self.browser.set_access.assert_not_awaited()

    async def test_close_switches_to_provider_selection_or_stops_stream_when_empty(self) -> None:
        await self.session.handle(OperatorCommand("close_page"))
        self.assertEqual(
            self.trace,
            [
                "select:owner:next",
                "stop",
                "start:owner:next",
                "state:owner",
            ],
        )
        self.browser.page_action.assert_awaited_once_with("owner", "initial", "close_page")
        self.trace.clear()
        self.browser.selected.return_value = ""
        await self.session.handle(OperatorCommand("close_page"))
        self.assertEqual(self.trace, ["stop", "state:owner"])
        self.assertEqual(self.session.selection.page_id, "")
