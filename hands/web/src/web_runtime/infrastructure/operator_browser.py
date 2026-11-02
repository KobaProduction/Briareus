"""Translate the existing browser provider into the operator application port."""

from dataclasses import dataclass

from web_runtime.domain.operator import MouseInput, OperatorOwner
from web_runtime.infrastructure.operator_runtime import OperatorBrowserRuntime


@dataclass(frozen=True)
class BrowserOperator:
    browser: OperatorBrowserRuntime

    async def acquire(self) -> OperatorOwner:
        result = await self.browser.operator_acquire()
        return OperatorOwner(result.owner_token, result.selected_page_id)

    async def release(self, owner: str) -> None:
        await self.browser.operator_release(owner)

    async def selected(self, owner: str) -> str:
        state = await self.browser.operator_state(owner)
        return state.selected_page_id

    async def select(self, owner: str, page: str) -> None:
        await self.browser.operator_select_page(owner, page)

    async def set_label(self, owner: str, page: str, label: str) -> None:
        await self.browser.operator_set_page_label(owner, page, label)

    async def set_access(self, owner: str, scope: str, page: str, allowed: bool) -> None:
        if scope == "set_page_agent_access":
            await self.browser.operator_set_page_agent_access(owner, page, allowed)
        elif scope == "set_agent_access":
            await self.browser.operator_set_agent_access(owner, allowed)
        else:
            await self.browser.operator_set_developer_access(owner, allowed)

    async def navigate(self, owner: str, page: str, url: str) -> None:
        await self.browser.operator_navigate(owner, page, url)

    async def new_page(self, owner: str, url: str) -> str:
        result = await self.browser.operator_new_page(owner, url)
        return result.page_id

    async def reopen_page(self, owner: str) -> str:
        result = await self.browser.operator_reopen_closed_page(owner)
        return result.page_id

    async def clean_browser(self, owner: str) -> str:
        result = await self.browser.operator_clean_browser(owner)
        return result.selected_page_id

    async def page_action(self, owner: str, page: str, action: str) -> None:
        handlers = {
            "clean_app": self.browser.operator_clean_app,
            "back": self.browser.operator_back,
            "reload": self.browser.operator_reload,
            "close_page": self.browser.operator_close_page,
        }
        await handlers[action](owner, page)

    async def mouse(self, owner: str, page: str, event: MouseInput) -> None:
        await self.browser.operator_mouse(
            owner,
            page,
            event_type=event.event_type,
            x=event.x,
            y=event.y,
            button=event.button,
            click_count=event.click_count,
            delta_x=event.delta_x,
            delta_y=event.delta_y,
        )

    async def key(self, owner: str, page: str, key: str) -> None:
        await self.browser.operator_key(owner, page, key)

    async def text(self, owner: str, page: str, text: str) -> None:
        await self.browser.operator_text(owner, page, text)
