"""Compatibility API for the bounded Web runtime implementation."""

import asyncio as asyncio
from contextlib import suppress as suppress
from dataclasses import dataclass as dataclass
from dataclasses import field as field

from playwright.async_api import CDPSession as CDPSession
from pydantic import ValidationError as ValidationError
from starlette.websockets import WebSocket as WebSocket

from modules.web.browser import BrowserManager as BrowserManager
from modules.web.domain.screencast import ScreenFrame as ScreenFrame
from web_runtime.infrastructure.operator_stream import (
    BrowserOperatorEvents as BrowserOperatorEvents,
)
from web_runtime.infrastructure.operator_stream import FrameReceiver as FrameReceiver
from web_runtime.infrastructure.operator_stream import consume_task as consume_task

from .operator_events import OperatorFrameEvent as OperatorFrameEvent
from .operator_events import OperatorStateEvent as OperatorStateEvent
from .operator_events import ScreencastFrame as ScreencastFrame
from .operator_events import ScreencastMetadata as ScreencastMetadata
from .operator_events import ScreencastSession as ScreencastSession
