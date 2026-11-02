"""Original provider tools with fresh typed custody and policies on every call."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Protocol

from mcp.types import CallToolRequestParams, CallToolResult

from node_protocol.provider_context import InvocationPolicies

from .account_lease import InvocationAccounts
from .provider_ipc import PreparationReady, ProviderCommand
from .provider_results import ProviderReply, provider_failure, provider_result


class ProviderDispatch(Protocol):
    def configure(self, policies: InvocationPolicies | None) -> None: ...
    async def call(self, call: CallToolRequestParams) -> CallToolResult: ...
    def clear(self) -> None: ...


def _require_provider_sandbox() -> None:
    os.chdir("/project-data")
    facts = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        os.geteuid() != 1000
        or int(facts["CapEff"].strip(), 16) != 0
        or facts["NoNewPrivs"].strip() != "1"
        or not os.statvfs("/").f_flag & os.ST_RDONLY
        or Path.cwd() != Path("/project-data")
    ):
        raise ValueError("Unprivileged project-scoped child required")


def _read_command(stream: BinaryIO) -> ProviderCommand | None:
    raw = stream.readline(131073)
    if not raw:
        return None
    if not raw.endswith(b"\n") or len(raw) > 131072:
        raise ValueError("Bounded private invocation required")
    request = ProviderCommand.model_validate_json(raw)
    if request.id.version != 4 or not 0 < request.expires_at - time.time() <= 5:
        raise ValueError("Current exact provider invocation required")
    return request


async def _execute(
    dispatch: ProviderDispatch,
    accounts: InvocationAccounts,
    request: ProviderCommand,
    failure_code: str,
) -> CallToolResult:
    try:
        accounts.bind(request.context.accounts)
        if "policies" in request.context.model_fields_set and request.context.policies is None:
            raise ValueError("Concrete current provider policy required")
        dispatch.configure(request.context.policies)
        return provider_result(await dispatch.call(request.call))
    except Exception:
        return provider_failure(failure_code)
    finally:
        dispatch.clear()
        accounts.clear()


async def run_provider_child(
    factory: Callable[[InvocationAccounts], ProviderDispatch], failure_code: str
) -> None:
    _require_provider_sandbox()
    accounts = InvocationAccounts(())
    dispatch = factory(accounts)
    print(PreparationReady(ready=True).model_dump_json(), flush=True)
    while (request := _read_command(sys.stdin.buffer)) is not None:
        result = await _execute(dispatch, accounts, request, failure_code)
        if not request.background and request.expires_at <= time.time():
            raise ValueError("Provider outcome expired")
        print(ProviderReply(id=request.id, result=result).encode(), flush=True)
        accounts = InvocationAccounts(())
        dispatch = factory(accounts)
