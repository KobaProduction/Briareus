"""Typed private-browser ports; production profile and deferred use cases remain real."""

import asyncio
import hashlib
import json
import time
import unittest
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult, Tool

from hand_runtime.application.deferred_operations import DeferredOperations
from hand_runtime.process_lease import ProcessLease
from hand_runtime.process_lease_application import ProcessLeaseController
from node_protocol.control import canonical
from node_protocol.effect import NodeEffectPermit
from web_hand.infrastructure.browser_ipc import BrowserReply, WebOperationView
from web_hand.node_supervisor import WebSupervisor


@dataclass
class SupervisorFixture:
    browser: WebSupervisor
    permit: NodeEffectPermit
    finish: asyncio.Event
    grants: AsyncMock
    exchange: AsyncMock
    stop: AsyncMock
    start: AsyncMock

    async def complete(self) -> None:
        await asyncio.wait_for(
            asyncio.gather(*self.browser.deferred._tasks.values(), return_exceptions=True), 1
        )


def operation(reply: BrowserReply) -> WebOperationView:
    assert reply.result is not None
    return WebOperationView.model_validate_json(json.dumps(reply.result.structured_content))


def supervisor_fixture(case: unittest.TestCase, *, warm: bool = False) -> SupervisorFixture:
    now = int(time.time())
    permit = NodeEffectPermit(
        module="web",
        node_uuid=uuid4(),
        placement_uuid=uuid4(),
        project_uuid=uuid4(),
        workspace_uuid=uuid4(),
        actor_uuid=uuid4(),
        agent_session_uuid=uuid4(),
        request_uuid=uuid4(),
        grant_revision=2,
        fingerprint="a" * 64,
        body_digest="b" * 64,
        bearer_digest="c" * 64,
        arguments_digest="d" * 64,
        method="tools/call",
        tool="local_browser_status",
        resource_id="fixture:" + "x" * 80,
        issued_at=now,
        expires_at=now + 4,
    )
    identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
    browser = WebSupervisor.__new__(WebSupervisor)
    browser.lock = asyncio.Lock()
    browser.status_warm, browser.child_ready = warm, True
    browser.status_task, browser.warming_task = None, None
    browser.metadata = [
        Tool.model_validate({"name": "local_browser_open", "inputSchema": {"type": "object"}})
    ]
    browser.profile_key = hashlib.sha256(canonical(identity[:2])).hexdigest()
    browser.profile = Path("/browser") / ("session-" + browser.profile_key)
    browser.child = Mock(spec=asyncio.subprocess.Process, returncode=None)
    browser.process_lease = ProcessLease.__new__(ProcessLease)
    ProcessLeaseController.__init__(browser.process_lease, 1000)
    browser.process_lease.identity = identity
    finish = asyncio.Event()

    async def grant(owner: tuple[str, str, int], _expires: float) -> bool:
        browser.process_lease.identity = owner
        return True

    async def exchange(
        _call: CallToolRequestParams,
        evidence: NodeEffectPermit,
        *,
        startup: bool = False,
        background: bool = False,
    ) -> BrowserReply:
        assert startup or background
        await finish.wait()
        return BrowserReply(
            id=evidence.request_uuid,
            result=CallToolResult(
                content=[],
                structured_content={"result": {"running": True}},
                is_error=False,
            ),
        )

    async def stop() -> None:
        browser.deferred.interrupt()
        for task in (browser.warming_task, browser.status_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                with suppress(asyncio.CancelledError, ValueError):
                    await task
        browser.warming_task = browser.status_task = None
        browser.status_warm = browser.child_ready = False
        browser.process_lease.identity = None
        browser.child = None

    async def start(key: str | None) -> None:
        browser.profile_key = key
        browser.profile = Path("/browser") / ("session-" + (key or "metadata"))
        browser.child = Mock(spec=asyncio.subprocess.Process, returncode=None)
        browser.child_ready = True

    grants, dispatch = AsyncMock(side_effect=grant), AsyncMock(side_effect=exchange)
    stopping, starting = AsyncMock(side_effect=stop), AsyncMock(side_effect=start)
    for owner, name, value in (
        (browser.process_lease, "grant", grants),
        (browser, "exchange", dispatch),
        (browser, "stop", stopping),
        (browser, "start", starting),
    ):
        case.enterContext(patch.object(owner, name, value))
    browser.deferred = DeferredOperations(
        boot=uuid4(),
        lock=browser.lock,
        lease=browser.process_lease,
        ready=lambda: browser.child_ready,
        stop=browser.stop,
        recover=lambda: browser.prepare_profile(browser.profile_key),
        clock=time.time,
        timeout=lambda: None,
    )
    return SupervisorFixture(browser, permit, finish, grants, dispatch, stopping, starting)
