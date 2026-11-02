"""The single legacy credential primitive adapter; never a Rauthy credential authority."""

import asyncio
import hashlib
import hmac

from common.credential_primitives import hash_password, random_token, token_hash, verify_password
from identity.application.limited_login import LoginThrottleKeys


class LegacyCredentials:
    def random_token(self) -> str:
        return random_token()

    def token_digest(self, token: str) -> str:
        return token_hash(token)

    async def password_digest(self, password: str) -> str:
        return await asyncio.to_thread(hash_password, password)

    async def verify(self, password: str, digest: str) -> bool:
        return await asyncio.to_thread(verify_password, password, digest)

    def keys(self, username: str, source: str, pepper: bytes) -> LoginThrottleKeys:
        normalized = username.strip().casefold()[:128]
        origin = source[:128]
        identity = hmac.new(
            pepper, ("identity:" + normalized + "\0" + origin).encode(), hashlib.sha256
        ).hexdigest()
        source_key = hmac.new(pepper, ("source:" + origin).encode(), hashlib.sha256).hexdigest()
        return LoginThrottleKeys(identity, source_key)
