"""Compatibility API for the canonical shared Files client implementation."""

from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from uuid import UUID as UUID

from project_runtime_client.files.domain.read_witness import (
    FileContentBinding as FileContentBinding,
)
from project_runtime_client.files.domain.read_witness import NativeReadBinding as NativeReadBinding
from project_runtime_client.files.domain.read_witness import (
    ReadWitnessChanged as ReadWitnessChanged,
)
from project_runtime_client.files.domain.read_witness import (
    ReadWitnessExpectation as ReadWitnessExpectation,
)
from project_runtime_client.files.domain.read_witness import (
    ReadWitnessObservation as ReadWitnessObservation,
)
from project_runtime_client.files.domain.read_witness import (
    require_current_witness as require_current_witness,
)
