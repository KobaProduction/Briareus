"""A warm browser may bind once; a different session must destroy its runtime."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

LeaseIdentity = tuple[str, str, int] | tuple[Literal["human"], str, str, int]


class ProfileAction(Enum):
    READY = "ready"
    BIND_WARM = "bind_warm"
    REPLACE = "replace"
    PREPARE = "prepare"


@dataclass(frozen=True, slots=True)
class ProfileObservation:
    profile_key: str | None
    lease_identity: LeaseIdentity | None
    metadata_ready: bool
    child_running: bool

    def action(self, profile_key: str, identity: LeaseIdentity) -> ProfileAction:
        if self.profile_key is None and self.lease_identity is None and self.metadata_ready:
            return ProfileAction.BIND_WARM
        if self.profile_key != profile_key or self.lease_identity not in {None, identity}:
            return ProfileAction.REPLACE
        if not self.child_running or not self.metadata_ready:
            return ProfileAction.PREPARE
        return ProfileAction.READY
