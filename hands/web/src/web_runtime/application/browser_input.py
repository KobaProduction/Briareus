"""Apply one human input through the existing exclusive browser operator port."""

from dataclasses import dataclass, replace

from web_runtime.application.operator_session import OperatorBrowser
from web_runtime.domain.operator import OperatorCommand, OperatorSelection, OperatorViolation


@dataclass(frozen=True, slots=True)
class ApplyBrowserInput:
    browser: OperatorBrowser

    async def execute(self, commands: tuple[OperatorCommand, ...]) -> None:
        if not 1 <= len(commands) <= 4:
            raise OperatorViolation("Bounded browser input batch required")
        page_id = commands[0].page_id
        if not page_id or any(
            command.action not in {"click", "mouse", "key", "text"} or command.page_id != page_id
            for command in commands
        ):
            raise OperatorViolation("One selected browser input target required")
        owner = await self.browser.acquire()
        try:
            await self.browser.select(owner.token, page_id)
            page = OperatorSelection(page_id).input_target(page_id)
            for command in commands:
                await self._input(owner.token, page, command)
        finally:
            await self.browser.release(owner.token)

    async def _input(self, owner: str, page: str, command: OperatorCommand) -> None:
        if command.action == "key":
            await self.browser.key(owner, page, command.value)
        elif command.action == "text":
            await self.browser.text(owner, page, command.value)
        else:
            mouse = command.mouse
            if mouse is None:
                raise OperatorViolation("Browser pointer input required")
            await self.browser.mouse(owner, page, mouse)
            if command.action == "click":
                await self.browser.mouse(owner, page, replace(mouse, event_type="mouseReleased"))
