"""Compatibility API for the bounded Web runtime implementation."""

from dataclasses import dataclass as dataclass
from typing import Protocol as Protocol

from modules.web.domain.developer_sync import ExtensionSyncReport as ExtensionSyncReport
from web_runtime.application.developer_sync import ManagedExtensionState as ManagedExtensionState
from web_runtime.application.developer_sync import ReconcileDeveloperSync as ReconcileDeveloperSync
