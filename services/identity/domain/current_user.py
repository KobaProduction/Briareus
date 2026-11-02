"""Current legacy user facts needed to fence an already verified bearer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUserSnapshot:
    enabled: bool
    deleted: bool
    credential_version: int

    def current(self, expected_credential_version: int) -> bool:
        return (
            self.enabled
            and not self.deleted
            and self.credential_version == expected_credential_version
        )
