"""Owner wire identities and fail-closed protocol rejection."""

from typing import Literal
from uuid import UUID

OwnerName = Literal[
    "identity", "access", "platform", "resources", "files", "runtime", "reverse", "ingest"
]


class OwnerAuthorityUnavailable(RuntimeError):
    """Security-sensitive effect cannot proceed without CURRENT source proof."""


def _uuid_v4(value: object) -> bool:
    return isinstance(value, UUID) and value.version == 4
