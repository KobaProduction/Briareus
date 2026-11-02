"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from uuid import UUID as UUID

from project_runtime_client.domain.owner_wire import (
    A11OwnerWireNotAccepted as A11OwnerWireNotAccepted,
)
from project_runtime_client.domain.owner_wire import OwnerPeerBinding as OwnerPeerBinding
from project_runtime_client.domain.owner_wire import require_catalog_query as require_catalog_query
from project_runtime_client.domain.owner_wire import (
    require_complete_lifecycle as require_complete_lifecycle,
)
from project_runtime_client.domain.owner_wire import (
    require_files_reservation as require_files_reservation,
)
from project_runtime_client.domain.owner_wire import require_phase as require_phase
from project_runtime_client.domain.owner_wire import uuid_v4 as uuid_v4
