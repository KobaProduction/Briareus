"""Browser lifecycle intent, independent of MCP tools and argument documents."""

from dataclasses import dataclass
from enum import Enum


class BrowserAction(Enum):
    CALL = "call"
    STATUS = "status"
    START_OPERATION = "start_operation"
    CONTROL_OPERATION = "control_operation"


@dataclass(frozen=True, slots=True)
class BrowserIntent:
    action: BrowserAction
    empty_arguments: bool
