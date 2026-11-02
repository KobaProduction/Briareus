"""Authority facts and admission rules for the retained administrative session."""

from dataclasses import dataclass
from uuid import UUID


class WebIdentityUnavailable(Exception):
    pass


class WebInvalidCredentials(Exception):
    pass


class WebAdministratorRequired(Exception):
    pass


class WebUserDisabled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WebUser:
    id: UUID
    username: str
    role: str
    enabled: bool

    def require_login(self) -> None:
        if not self.enabled or self.role != "superuser":
            raise WebAdministratorRequired

    def require_current(self) -> None:
        if not self.enabled:
            raise WebUserDisabled
        if self.role != "superuser":
            raise WebAdministratorRequired
