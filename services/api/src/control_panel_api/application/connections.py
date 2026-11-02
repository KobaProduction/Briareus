"""Human connection administration with current operator authority."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from control_panel_api.application._constructor_bindings import _ManagementBinding
from control_panel_api.domain.operator_context import operator_continues
from control_panel_api.domain.panel_protocol import PanelContext
from runtime_peer.connection_contracts import (
    ConnectionConfigurationInput,
    GitLabPolicyForm,
    GitPolicyForm,
    _configuration_input,
)
from runtime_peer.connection_form_schema import ConnectionSchema as ConnectionSchema


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_uuid: UUID
    action: Literal["forms", "list", "verify", "create", "update", "delete", "check"]
    connection_uuid: UUID | None = None
    alias: str = Field(default="", max_length=128)
    credential: SecretStr = Field(default=SecretStr(""), repr=False)
    configuration: ConnectionConfigurationInput | None = None
    expected_revision: int | None = Field(default=None, strict=True, ge=1)
    cursor: str | None = Field(default=None, max_length=1024)

    configuration_input = field_validator("configuration", mode="before")(
        staticmethod(_configuration_input)
    )


class ConnectionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    provider: str
    auth_type: str
    base_url: str | None = None
    external_id: str | None = None
    ca_cert_pem: str | None = None
    git_policy: GitPolicyForm | GitLabPolicyForm | None = None


class ConnectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    alias: str
    provider: str
    base_url: str
    auth_type: str
    credential_configured: bool
    revision: int
    configuration: ConnectionConfiguration


class ConnectionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: tuple[ConnectionItem, ...]
    has_more: bool
    next_cursor: str | None


class ConnectionDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: ConnectionItem


class ConnectionDeleted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted: Literal[True]


class ConnectionProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    message: str | None = None
    identity: str | None = None


ConnectionOutput = (
    ConnectionPage | ConnectionDetail | ConnectionDeleted | ConnectionProbe | ConnectionSchema
)


@dataclass(frozen=True, slots=True)
class ConnectionFailure:
    status: int
    code: str


@dataclass(frozen=True, slots=True)
class ConnectionReceipt:
    status: int
    value: ConnectionOutput | None = None


class ConnectionAuthority(Protocol):
    async def current(self, project: UUID) -> PanelContext | ConnectionFailure: ...


class ConnectionOwner(Protocol):
    async def execute(
        self, command: ConnectionInput, context: PanelContext
    ) -> ConnectionReceipt: ...


class ConnectionEvents(Protocol):
    async def committed(
        self, command: ConnectionInput, result: ConnectionOutput, actor: UUID
    ) -> None: ...


class ManageConnections(_ManagementBinding[ConnectionAuthority, ConnectionOwner, ConnectionEvents]):
    async def execute(self, command: ConnectionInput) -> ConnectionOutput | ConnectionFailure:
        original = await self._authority.current(command.project_uuid)
        if isinstance(original, ConnectionFailure):
            return original
        if original.proof.role != "operator":
            return ConnectionFailure(403, "CONNECTION_OPERATOR_REQUIRED")
        deadline = min(original.session.expires_at, original.proof.expires_at)
        if deadline <= datetime.now(UTC):
            return ConnectionFailure(403, "CONNECTION_ACTOR_CHANGED")
        if self._owner is None:
            return ConnectionFailure(503, "CONNECTION_OWNER_UNAVAILABLE")
        try:
            receipt = await self._owner.execute(command, original)
        except Exception:
            return ConnectionFailure(503, "CONNECTION_OWNER_UNAVAILABLE")
        if receipt.status != 200 or receipt.value is None:
            return self._failure(receipt.status)
        fresh = await self._authority.current(command.project_uuid)
        if isinstance(fresh, ConnectionFailure):
            return fresh
        if not operator_continues(original, fresh, deadline):
            return ConnectionFailure(403, "CONNECTION_ACTOR_CHANGED")
        if command.action in {"create", "update", "delete"}:
            await self._events.committed(command, receipt.value, original.proof.user_uuid)
        return receipt.value

    @staticmethod
    def _failure(status: int) -> ConnectionFailure:
        codes = {
            403: "CONNECTION_PERMISSION_DENIED",
            404: "CONNECTION_NOT_FOUND",
            409: "CONNECTION_ALREADY_EXISTS",
            422: "CONNECTION_INPUT_INVALID",
        }
        return ConnectionFailure(
            status if status in codes else 503, codes.get(status, "CONNECTION_OWNER_UNAVAILABLE")
        )
