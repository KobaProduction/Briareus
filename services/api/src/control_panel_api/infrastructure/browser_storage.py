"""One browser Valkey client, lifecycle and hashed token namespace."""

from __future__ import annotations

import re
from hashlib import sha256

from pydantic import SecretStr
from valkey.asyncio import Valkey

BROWSER_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")


class BrowserStorageContext:
    def __init__(self, *, password: SecretStr, client: Valkey | None = None) -> None:
        raw = password.get_secret_value()
        if re.fullmatch(r"[a-f0-9]{64}", raw) is None:
            raise ValueError("OIDC transaction store requires the protected Valkey credential")
        self.client = client or Valkey(
            host="briareus-valkey",
            port=6379,
            password=raw,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
            health_check_interval=30,
        )
        self._owned = client is None

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()

    @staticmethod
    def key(scope: str, token: str) -> str:
        if BROWSER_TOKEN.fullmatch(token) is None:
            raise ValueError("untrusted OIDC browser token")
        return "briareus:panel:oidc:" + scope + ":" + sha256(token.encode("ascii")).hexdigest()
