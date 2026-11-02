"""Human input reuses the existing selected-page operator and always releases it."""

import unittest
from unittest.mock import AsyncMock, Mock, call

from pydantic import ValidationError

from runtime_peer.browser_arguments import BrowserInputArguments
from web_hand.node_supervisor import WebSupervisor
from web_runtime.application.browser_input import ApplyBrowserInput
from web_runtime.application.operator_session import OperatorBrowser
from web_runtime.domain.operator import OperatorCommand, OperatorOwner
from web_runtime.presentation.browser_input import input_command


class HumanBrowserInputTests(unittest.IsolatedAsyncioTestCase):
    def ports(self) -> Mock:
        browser = Mock(spec=OperatorBrowser)
        browser.acquire = AsyncMock(return_value=OperatorOwner("owner", "previous"))
        browser.release = AsyncMock()
        browser.select = AsyncMock()
        browser.mouse = AsyncMock()
        browser.key = AsyncMock()
        browser.text = AsyncMock()
        return browser

    async def test_pointer_and_text_keep_one_selected_target_and_order(self) -> None:
        arguments = BrowserInputArguments.model_validate(
            {
                "page_id": "page",
                "events": [
                    {"kind": "click", "x": 120, "y": 80, "button": "left", "click_count": 1},
                    {"kind": "text", "text": "search"},
                    {"kind": "key", "key": "Enter"},
                ],
            }
        )
        browser = self.ports()
        commands = tuple(input_command(arguments.page_id, event) for event in arguments.events)
        await ApplyBrowserInput(browser).execute(commands)
        browser.acquire.assert_awaited_once()
        browser.select.assert_awaited_once_with("owner", "page")
        self.assertEqual(len(browser.mouse.await_args_list), 2)
        self.assertEqual(browser.mouse.await_args_list[0].args[2].event_type, "mousePressed")
        self.assertEqual(browser.mouse.await_args_list[1].args[2].event_type, "mouseReleased")
        browser.text.assert_awaited_once_with("owner", "page", "search")
        browser.key.assert_awaited_once_with("owner", "page", "Enter")
        browser.release.assert_awaited_once_with("owner")

    async def test_failed_input_releases_operator_without_repeating_input(self) -> None:
        browser = self.ports()
        browser.key.side_effect = ValueError("native input failed")
        with self.assertRaises(ValueError):
            await ApplyBrowserInput(browser).execute((OperatorCommand("key", "page", "Enter"),))
        browser.key.assert_has_awaits([call("owner", "page", "Enter")])
        browser.release.assert_awaited_once_with("owner")

    async def test_mixed_pages_are_rejected_before_operator_acquisition(self) -> None:
        browser = self.ports()
        with self.assertRaises(ValueError):
            await ApplyBrowserInput(browser).execute(
                (
                    OperatorCommand("text", "one", "first"),
                    OperatorCommand("text", "other", "second"),
                )
            )
        browser.acquire.assert_not_awaited()

    def test_unbounded_or_nonfinite_input_is_rejected_at_wire_boundary(self) -> None:
        for event in (
            {"kind": "click", "x": float("nan"), "y": 10},
            {"kind": "click", "x": -1, "y": 10},
            {"kind": "text", "text": "x" * 1025},
            {"kind": "key", "key": ""},
        ):
            with self.subTest(event_kind=event["kind"]), self.assertRaises(ValidationError):
                BrowserInputArguments.model_validate({"page_id": "page", "events": [event]})
        with self.assertRaises(ValidationError):
            BrowserInputArguments.model_validate({"page_id": "page", "events": []})

    async def test_agent_permit_cannot_invoke_human_operator_even_in_background(self) -> None:
        from mcp.types import CallToolRequestParams
        from supervisor_fixture import supervisor_fixture

        fixture = supervisor_fixture(self, warm=True)
        try:
            with self.assertRaisesRegex(ValueError, "signed project-user"):
                await WebSupervisor.exchange(
                    fixture.browser,
                    CallToolRequestParams(name="local_browser_input", arguments={}),
                    fixture.permit,
                    background=True,
                )
            fixture.grants.assert_not_awaited()
        finally:
            await fixture.browser.stop()
            await fixture.complete()
