"""Compatibility API for the bounded Web runtime implementation."""

from collections.abc import Awaitable as Awaitable
from collections.abc import Callable as Callable
from dataclasses import dataclass as dataclass
from typing import Protocol as Protocol
from typing import Self as Self

from modules.web.domain.operator import MouseInput as MouseInput
from modules.web.domain.operator import OperatorCommand as OperatorCommand
from modules.web.domain.operator import OperatorOwner as OperatorOwner
from modules.web.domain.operator import OperatorSelection as OperatorSelection
from modules.web.domain.operator import OperatorViolation as OperatorViolation
from web_runtime.application.operator_session import OperatorBrowser as OperatorBrowser
from web_runtime.application.operator_session import OperatorEvents as OperatorEvents
from web_runtime.application.operator_session import OperatorSession as OperatorSession
