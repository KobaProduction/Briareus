"""Compatibility API for the bounded Web runtime implementation."""

from dataclasses import dataclass as dataclass

from web_runtime.domain.developer_sync import DeveloperSyncViolation as DeveloperSyncViolation
from web_runtime.domain.developer_sync import ExtensionFailure as ExtensionFailure
from web_runtime.domain.developer_sync import ExtensionSyncReport as ExtensionSyncReport
