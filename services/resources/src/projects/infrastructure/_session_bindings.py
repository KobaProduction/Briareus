"""Private typed transaction and cipher references for existing SQL owner sessions."""

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession


class _CipherSessionBinding:
    def __init__(self, tx: AsyncSession, cipher: Fernet) -> None:
        self._tx, self._cipher = tx, cipher
