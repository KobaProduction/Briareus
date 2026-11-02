"""Compatibility API for the bounded Web runtime implementation."""

import hmac as hmac
import json as json
from contextlib import suppress as suppress

from pydantic import ValidationError as ValidationError
from starlette.websockets import WebSocket as WebSocket
from starlette.websockets import WebSocketDisconnect as WebSocketDisconnect

from modules.web.application.operator_session import OperatorSession as OperatorSession
from modules.web.browser import BrowserError as BrowserError
from modules.web.browser import BrowserManager as BrowserManager
from modules.web.domain.operator import OperatorViolation as OperatorViolation
from modules.web.infrastructure.operator_browser import BrowserOperator as BrowserOperator
from modules.web.infrastructure.operator_codec import decode_command as decode_command
from modules.web.infrastructure.operator_events import OperatorErrorEvent as OperatorErrorEvent
from modules.web.infrastructure.operator_stream import (
    BrowserOperatorEvents as BrowserOperatorEvents,
)
from web_runtime.operator import _bearer_token as _bearer_token
from web_runtime.operator import _messages as _messages
from web_runtime.operator import browser_operator_websocket as browser_operator_websocket
