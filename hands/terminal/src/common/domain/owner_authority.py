"""Stable persistence-owner identities and the fail-closed authority rejection."""

from owner_protocol.domain.authority import (
    OwnerAuthorityUnavailable as OwnerAuthorityUnavailable,
)
from owner_protocol.domain.authority import (
    OwnerName as OwnerName,
)

OWNER_DB_NAMES: dict[OwnerName, str] = {
    "identity": "briareus_identity",
    "access": "briareus_access",
    "platform": "briareus_platform",
    "resources": "briareus_resources",
    "files": "briareus_files",
    "runtime": "briareus_runtime",
    "reverse": "briareus_reverse",
    "ingest": "briareus_ingest",
}
