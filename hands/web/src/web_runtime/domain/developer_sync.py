"""Native extension observations reconcile managed IDs before reporting partial failures."""

from dataclasses import dataclass


class DeveloperSyncViolation(ValueError):
    pass


@dataclass(frozen=True)
class ExtensionFailure:
    extension_id: str
    message: str


@dataclass(frozen=True)
class ExtensionSyncReport:
    eligible_ids: frozenset[str]
    failures: tuple[ExtensionFailure, ...]

    def managed_after(
        self,
        current: frozenset[str],
        requested: tuple[str, ...] | None,
    ) -> frozenset[str]:
        if requested is None:
            return self.eligible_ids
        selected = frozenset(requested)
        return (current - selected) | (self.eligible_ids & selected)

    def require_success(self) -> None:
        if self.failures:
            details = "; ".join(
                f"{failure.extension_id}: {failure.message}" for failure in self.failures[:5]
            )
            raise DeveloperSyncViolation(
                "Chromium userScripts access synchronization failed"
                + (f": {details}" if details else "")
            )
