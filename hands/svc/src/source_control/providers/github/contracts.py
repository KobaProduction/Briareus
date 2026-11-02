"""Typed account and callable boundaries for the reusable GitHub adapter."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from mcp.types import ToolAnnotations
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from service_runtime.account_contracts import AccountList, ResolvedAccount


class AccountAccess(Protocol):
    def list_accounts(self, *, provider: str | None = None) -> AccountList: ...

    def resolve_account(self, selector: str, *, provider: str) -> ResolvedAccount: ...


class ToolRegistrar(Protocol):
    def tool[**P, R: BaseModel | Awaitable[BaseModel]](
        self,
        *,
        title: str | None = None,
        annotations: ToolAnnotations | None = None,
        output_schema: JsonSchemaValue | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...
