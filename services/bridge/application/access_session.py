"""Per-call admission through the authoritative session validation port."""

from dataclasses import dataclass
from typing import Protocol

from bridge.domain.access_session import is_base_read_only
from common.access_contracts import OAuthContext, ValidationResult


@dataclass(frozen=True, slots=True)
class SessionToolAttempt:
    surface: str
    surface_id: int
    tool_name: str
    session_uid: str
    account_id: str
    read_only_hint: bool


class AccessValidationUnavailable(Exception):
    def __init__(self, error_type: str) -> None:
        self.error_type = error_type
        super().__init__("Access validation is temporarily unavailable.")


class SessionValidationPort(Protocol):
    async def validate(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        tool_name: str,
        requires_full_access: bool,
        account_id: str,
    ) -> ValidationResult: ...


class AdmitSessionTool:
    def __init__(self, validation: SessionValidationPort) -> None:
        self._validation = validation

    async def execute(self, context: OAuthContext, attempt: SessionToolAttempt) -> ValidationResult:
        read_only = is_base_read_only(
            attempt.surface,
            attempt.tool_name,
            read_only_hint=attempt.read_only_hint,
        )
        return await self._validation.validate(
            context=context,
            surface_id=attempt.surface_id,
            session_uid=attempt.session_uid,
            tool_name=attempt.tool_name,
            requires_full_access=not read_only,
            account_id=attempt.account_id,
        )
