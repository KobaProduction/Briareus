"""Compatibility API for the bounded Web runtime implementation."""

from typing import Literal as Literal

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field

from modules.web.browser_models import OperatorState as OperatorState
from modules.web.domain.screencast import FrameMetadata as FrameMetadata
from modules.web.domain.screencast import ScreenFrame as ScreenFrame
from web_runtime.infrastructure.operator_events import OperatorErrorEvent as OperatorErrorEvent
from web_runtime.infrastructure.operator_events import OperatorFrameEvent as OperatorFrameEvent
from web_runtime.infrastructure.operator_events import OperatorStateEvent as OperatorStateEvent
from web_runtime.infrastructure.operator_events import ScreencastFrame as ScreencastFrame
from web_runtime.infrastructure.operator_events import ScreencastMetadata as ScreencastMetadata
from web_runtime.infrastructure.operator_events import ScreencastSession as ScreencastSession
