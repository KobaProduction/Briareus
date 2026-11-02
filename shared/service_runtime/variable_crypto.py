"""Write the existing encrypted/plain content pair without owning its persistence."""

from typing import Protocol

from cryptography.fernet import Fernet
from pydantic import SecretStr


class _VariableWriteView(Protocol):
    is_secret: bool
    encrypted_value: str | None
    plain_value: str | None


def _write_variable_content(row: _VariableWriteView, value: SecretStr, cipher: Fernet) -> None:
    raw = value.get_secret_value()
    row.encrypted_value = cipher.encrypt(raw.encode()).decode() if row.is_secret else None
    row.plain_value = None if row.is_secret else raw
