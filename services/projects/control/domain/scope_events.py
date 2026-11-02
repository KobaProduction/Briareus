"""Safe source-event metadata; accepted scalars never confer execution rights."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from owner_protocol.domain.authority import _uuid_v4 as _uuid_v4_source

_uuid4 = _uuid_v4_source
del _uuid_v4_source


def _require_optional[T](values: tuple[T | None, ...], valid: Callable[[object], bool]) -> None:
    if any(value is not None and not valid(value) for value in values):
        raise ValueError("Invalid public scope-event metadata")


def _revision(value: object) -> bool:
    return type(value) is int and 0 <= value < 2**63


def _flag(value: object) -> bool:
    return isinstance(value, bool)


def _text(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None


def _native_identifier(value: object) -> bool:
    return _text(value) or _revision(value)


def _epoch(value: object) -> bool:
    return _uuid4(value) or _revision(value)


@dataclass(frozen=True, slots=True)
class ScopeEventDetails:
    approved: bool | None = None
    cleanup_required: bool | None = None
    enabled: bool | None = None
    job_status: str | None = None
    job_version: int | None = None
    lifecycle_status: str | None = None
    native_import_version: int | None = None
    native_project_id: str | int | None = None
    over_limit: bool | None = None
    owner_id: UUID | None = None
    owner_resource_revision: int | None = None
    owner_scope: str | None = None
    project_id: UUID | None = None
    quota_revision: int | None = None
    reconciliation_required: bool | None = None
    reservation_revision: int | None = None
    resource_id: UUID | None = None
    resource_version: int | None = None
    runtime_revision: int | None = None
    scope_epoch: UUID | int | None = None
    session_version: int | None = None
    source_file_version: int | None = None
    team_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_optional((self.owner_id, self.project_id, self.resource_id, self.team_id), _uuid4)
        _require_optional(
            (
                self.approved,
                self.cleanup_required,
                self.enabled,
                self.over_limit,
                self.reconciliation_required,
            ),
            _flag,
        )
        _require_optional(
            (
                self.job_version,
                self.native_import_version,
                self.owner_resource_revision,
                self.quota_revision,
                self.reservation_revision,
                self.resource_version,
                self.runtime_revision,
                self.session_version,
                self.source_file_version,
            ),
            _revision,
        )
        _require_optional((self.job_status, self.lifecycle_status, self.owner_scope), _text)
        _require_optional((self.native_project_id,), _native_identifier)
        _require_optional((self.scope_epoch,), _epoch)
