"""Compatibility API for the canonical shared Files client implementation."""

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict

from project_runtime_client.files.read_payloads import (
    FilesReadBusinessPayload as FilesReadBusinessPayload,
)
from project_runtime_client.files.read_payloads import (
    NativeReadBusinessObservation as NativeReadBusinessObservation,
)
