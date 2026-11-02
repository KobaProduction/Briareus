"""Variable content codec stays inside the legacy Catalog's persistence owner."""

from collections.abc import Callable

from cryptography.fernet import Fernet
from pydantic import SecretStr

from projects._resource_persistence import VariableRow
from service_runtime.variable_crypto import _write_variable_content

write_variable_content: Callable[[VariableRow, SecretStr, Fernet], None] = _write_variable_content
