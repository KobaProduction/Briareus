"""Current owner policy for each admitted provider effect."""

from dataclasses import dataclass
from enum import Enum


class SourceEffect(Enum):
    READ = "read"
    REMOTE_MUTATION = "remote_mutation"
    LOCAL_GIT = "local_git"


@dataclass(frozen=True)
class ProviderPolicy:
    remote_mutations: bool
    local_git: bool

    def require(self, effect: SourceEffect) -> None:
        allowed = (
            effect is SourceEffect.READ
            or (effect is SourceEffect.REMOTE_MUTATION and self.remote_mutations)
            or (effect is SourceEffect.LOCAL_GIT and self.local_git)
        )
        if not allowed:
            raise ValueError("Remote source mutation or local Git disabled by current owner policy")
