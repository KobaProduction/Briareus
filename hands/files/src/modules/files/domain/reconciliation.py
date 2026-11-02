"""Compatibility API for the canonical shared Files client implementation."""

from dataclasses import dataclass as dataclass

from project_runtime_client.files.domain.reconciliation import (
    ReconciliationObservation as ReconciliationObservation,
)
from project_runtime_client.files.domain.reconciliation import (
    ReconciliationRejected as ReconciliationRejected,
)
