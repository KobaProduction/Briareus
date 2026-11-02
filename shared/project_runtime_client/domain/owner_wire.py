"""A nominal wire command cannot substitute for accepted complete owner authority."""

from dataclasses import dataclass
from uuid import UUID

from owner_protocol.domain.authority import _uuid_v4 as _uuid_v4_source
from project_runtime_client.domain._code_error import _CodeError

uuid_v4 = _uuid_v4_source
del _uuid_v4_source


class A11OwnerWireNotAccepted(_CodeError, ValueError):
    def __init__(self, code: str = "A11_OWNER_OPERATION_NOT_ACCEPTED") -> None:
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OwnerPeerBinding:
    """Marshal identifiers of an already verified peer; this is not authentication."""

    service_id: UUID
    instance_uuid: UUID

    def __post_init__(self) -> None:
        if not uuid_v4(self.service_id) or not uuid_v4(self.instance_uuid):
            raise A11OwnerWireNotAccepted("A11_OWNER_VERIFIED_PEER_REQUIRED")


def require_complete_lifecycle(accepted: frozenset[str], required: frozenset[str]) -> None:
    if not required <= accepted:
        raise A11OwnerWireNotAccepted("A12_OWNER_COMPLETE_SIGNED_EFFECT_LIFECYCLE_REQUIRED")


def require_phase(observed: str, expected: str, code: str) -> None:
    if observed != expected:
        raise A11OwnerWireNotAccepted(code)


def require_files_reservation(expected_version: int, planned_bytes: int) -> None:
    if expected_version != 0 or planned_bytes > 262144:
        raise A11OwnerWireNotAccepted("A11_FILES_UNAPPROVED_OVERWRITE_OR_SIZE")


def require_catalog_query(limit: int, scope: str) -> None:
    if limit > 100 or scope != "all":
        raise A11OwnerWireNotAccepted("A11_CATALOG_READ_QUERY_UNSUPPORTED")
