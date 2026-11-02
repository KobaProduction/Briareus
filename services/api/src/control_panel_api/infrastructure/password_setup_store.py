"""Valkey one-use preparation claims; private fields retain their existing wire keys."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from valkey.exceptions import ValkeyError

from control_panel_api.domain.password_setup import PasswordPreparation, PasswordSetupUnavailable
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext


class StoredPasswordPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    user_id: str
    code: str = Field(repr=False)
    csrf: str = Field(repr=False)
    cookie: str = Field(repr=False)
    expires_at: float

    def preparation(self) -> PasswordPreparation:
        return PasswordPreparation(
            self.user_id,
            SecretStr(self.code),
            SecretStr(self.csrf),
            SecretStr(self.cookie),
            self.expires_at,
        )


def _decode(raw: object) -> PasswordPreparation | None:
    if not isinstance(raw, str):
        return None
    return StoredPasswordPreparation.model_validate_json(raw).preparation()


class ValkeyPasswordSetupStore:
    def __init__(self, storage: BrowserStorageContext) -> None:
        self._storage = storage

    async def peek(self, ticket: str) -> PasswordPreparation | None:
        try:
            raw = await self._storage.client.get(self._storage.key("password-setup", ticket))
        except ValkeyError:
            raise PasswordSetupUnavailable from None
        return _decode(raw)

    async def claim(self, ticket: str) -> PasswordPreparation | None:
        try:
            raw = await self._storage.client.getdel(self._storage.key("password-setup", ticket))
        except ValkeyError:
            raise PasswordSetupUnavailable from None
        return _decode(raw)

    async def save(self, ticket: str, preparation: PasswordPreparation, age: int) -> bool:
        data = StoredPasswordPreparation(
            user_id=preparation.user_id,
            code=preparation.code.get_secret_value(),
            csrf=preparation.csrf.get_secret_value(),
            cookie=preparation.cookie.get_secret_value(),
            expires_at=preparation.expires_at,
        )
        try:
            saved = await self._storage.client.set(
                self._storage.key("password-setup", ticket),
                data.model_dump_json(),
                ex=age,
                nx=True,
            )
        except ValkeyError:
            raise PasswordSetupUnavailable from None
        return bool(saved)

    async def delete(self, ticket: str) -> None:
        try:
            await self._storage.client.delete(self._storage.key("password-setup", ticket))
        except ValkeyError:
            raise PasswordSetupUnavailable from None
