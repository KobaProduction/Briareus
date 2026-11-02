"""Project connection custody and verified provider identity facts."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID


class ConnectionFailure(ValueError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass(frozen=True)
class ProviderProbe:
    provider: str
    base_url: str
    token: str = field(repr=False)
    auth_type: str
    external_id: str = ""
    ca_cert_pem: str = ""


@dataclass(frozen=True)
class ProviderCheck:
    status: Literal["connected", "denied", "unavailable"]
    message: str | None = None
    identity: str | None = None

    @classmethod
    def unavailable(cls, *, existing: bool = False) -> "ProviderCheck":
        message = (
            "\u041d\u0435 удалось проверить подключение; проверьте адрес и доступность провайдера"
            if existing
            else "Провайдер не подтвердил подключение"
        )
        return cls("unavailable", message)


@dataclass(frozen=True)
class ConnectionRevision:
    project_uuid: UUID
    connection_uuid: UUID
    expected_revision: int | None

    def require_identifier(self) -> None:
        if self.connection_uuid.version != 4:
            raise ConnectionFailure(422, "Connection UUID required")

    def require_matches(self, actual: int, *, deleting: bool = False) -> None:
        if self.expected_revision != actual:
            suffix = "deleting" if deleting else "editing"
            raise ConnectionFailure(409, "Connection changed; reload before " + suffix)


def require_connection_proof(expiry: datetime, now: datetime) -> None:
    if expiry <= now:
        raise ConnectionFailure(403, "Current Platform proof expired")
