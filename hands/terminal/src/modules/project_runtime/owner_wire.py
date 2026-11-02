"""Owner-local compatibility and codec boundary for shared runtime clients."""

from __future__ import annotations

from dataclasses import dataclass as dataclass
from typing import Literal as Literal

from pydantic import BaseModel as BaseModel

from modules.project_runtime.domain.owner_wire import (
    A11OwnerWireNotAccepted as A11OwnerWireNotAccepted,
)
from modules.project_runtime.domain.owner_wire import OwnerPeerBinding as OwnerPeerBinding
from modules.project_runtime.domain.owner_wire import require_catalog_query as require_catalog_query
from modules.project_runtime.domain.owner_wire import (
    require_complete_lifecycle as require_complete_lifecycle,
)
from modules.project_runtime.domain.owner_wire import (
    require_files_reservation as require_files_reservation,
)
from modules.project_runtime.domain.owner_wire import require_phase as require_phase
from project_runtime_client.owner_wire import _ACCEPTED_OWNER_PHASES as _ACCEPTED_OWNER_PHASES
from project_runtime_client.owner_wire import _REQUIRED_EFFECT_PHASES as _REQUIRED_EFFECT_PHASES
from project_runtime_client.owner_wire import A11EffectOwner as A11EffectOwner
from project_runtime_client.owner_wire import A11OwnerWire as A11OwnerWire
from project_runtime_client.owner_wire import OwnerPayloadAdapters as OwnerPayloadAdapters
from project_runtime_client.owner_wire import _catalog_wire as _catalog_wire
from project_runtime_client.owner_wire import _default_a11_owner_wire
from project_runtime_client.owner_wire import _encode_files_wire as _encode_files_wire
from project_runtime_client.owner_wire import _encode_reverse_wire as _encode_reverse_wire
from project_runtime_client.owner_wire import _execution_wire as _execution_wire
from project_runtime_client.owner_wire import _files_wire as _files_wire
from project_runtime_client.owner_wire import _peer as _peer
from project_runtime_client.owner_wire import _reverse_wire as _reverse_wire
from project_runtime_client.owner_wire import accepted_a11_owner_wire as _generic_a11_owner_wire
from project_runtime_client.owner_wire import (
    require_accepted_owner_lifecycle as require_accepted_owner_lifecycle,
)

from .infrastructure.owner_payloads import CatalogListPayload as CatalogListPayload
from .infrastructure.owner_payloads import FilesDispatchPayload as FilesDispatchPayload
from .infrastructure.owner_payloads import FilesReservePayload as FilesReservePayload
from .infrastructure.owner_payloads import FilesTransitionPayload as FilesTransitionPayload
from .infrastructure.owner_payloads import NativeDispatchPayload as NativeDispatchPayload
from .infrastructure.owner_payloads import NativeTransitionPayload as NativeTransitionPayload
from .infrastructure.owner_payloads import OwnerBusinessPayload as OwnerBusinessPayload
from .infrastructure.owner_payloads import RuntimeOpenPayload as RuntimeOpenPayload
from .infrastructure.owner_payloads import RuntimeRenewPayload as RuntimeRenewPayload
from .infrastructure.owner_payloads import RuntimeRevokePayload as RuntimeRevokePayload
from .owner_authorization import VerifiedOwnerRecipient as VerifiedOwnerRecipient

_encode_a11_owner_wire = _generic_a11_owner_wire
accepted_a11_owner_wire = _default_a11_owner_wire
