"""Prepare metadata without granting or renewing native effect authority."""

from enum import Enum
from typing import Protocol

from web_hand.domain.profile import LeaseIdentity, ProfileAction, ProfileObservation


class ProfileReadiness(Enum):
    READY = "ready"
    SESSION_PREPARING = "session_preparing"
    METADATA_PREPARING = "metadata_preparing"


class ProfileRuntime(Protocol):
    def profile_observation(self) -> ProfileObservation: ...
    def bind_warm_profile(self, profile_key: str) -> None: ...
    def prepare_profile(self, profile_key: str) -> None: ...


class PrepareProfile:
    def __init__(self, runtime: ProfileRuntime) -> None:
        self._runtime = runtime

    async def execute(self, profile_key: str, identity: LeaseIdentity) -> ProfileReadiness:
        action = self._runtime.profile_observation().action(profile_key, identity)
        if action is ProfileAction.BIND_WARM:
            self._runtime.bind_warm_profile(profile_key)
        elif action is ProfileAction.REPLACE:
            # The preparation task destroys the old runtime before starting the
            # replacement. Metadata cleanup must not consume an effect permit.
            self._runtime.prepare_profile(profile_key)
            return ProfileReadiness.SESSION_PREPARING
        elif action is ProfileAction.PREPARE:
            self._runtime.prepare_profile(profile_key)
            return ProfileReadiness.METADATA_PREPARING
        return ProfileReadiness.READY
