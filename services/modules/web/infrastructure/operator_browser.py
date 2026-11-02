"""Compatibility API for the bounded Web runtime implementation."""

from dataclasses import dataclass as dataclass

from modules.web.browser import BrowserManager as BrowserManager
from modules.web.domain.operator import MouseInput as MouseInput
from modules.web.domain.operator import OperatorOwner as OperatorOwner
from web_runtime.infrastructure.operator_browser import BrowserOperator as BrowserOperator
