"""Confidential variable content stays inside the Catalog persistence adapter."""

from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from common.platform_errors import AccessDenied
from projects._resource_persistence import VariableRow
from service_runtime.variable_crypto import _write_variable_content

write_variable_content: Callable[[VariableRow, SecretStr, Fernet], None] = _write_variable_content


def read_variable_content(row: VariableRow, cipher: Fernet) -> SecretStr:
    try:
        if row.is_secret:
            if row.encrypted_value is None:
                raise InvalidToken
            return SecretStr(cipher.decrypt(row.encrypted_value.encode()).decode())
        if row.plain_value is None:
            raise InvalidToken
        return SecretStr(row.plain_value)
    except (InvalidToken, UnicodeDecodeError):
        raise AccessDenied("variable content integrity unavailable") from None
