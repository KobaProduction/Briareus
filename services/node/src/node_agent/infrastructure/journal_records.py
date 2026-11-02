"""Explicit shared transport records used by the remote journal adapter."""

from node_protocol.journal import (
    JournalConfiguration as ConfigurationRecord,
)
from node_protocol.journal import (
    JournalEvent as JournalEvent,
)
from node_protocol.journal import (
    JournalOperation as OperationRecord,
)

__all__ = ["ConfigurationRecord", "JournalEvent", "OperationRecord"]
