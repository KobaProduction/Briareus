"""A provider credential is reusable only before the existing refresh margin."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class InstallationCredential:
    token: str = field(repr=False)
    expires_at: float

    def reusable_at(self, now: float) -> bool:
        return self.expires_at > now + 120
