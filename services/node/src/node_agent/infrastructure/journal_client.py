"""One signed RPC per journal operation; transport failures never retry effects."""

import asyncio
import logging
import time
from typing import Protocol
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from node_agent.application.journal_errors import JournalUnavailable as JournalUnavailable
from node_agent.domain.placement import OperationConflict
from node_protocol.journal import (
    MAX_REQUEST_BYTES,
    JournalAction,
    JournalRequest,
    JournalResult,
    SignedJournalReply,
    SignedJournalRequest,
    sign_request,
    verify_reply,
)


class JournalRpc(Protocol):
    async def exchange(self, request: SignedJournalRequest) -> SignedJournalReply: ...

    async def close(self) -> None: ...


class SignedJournalClient:
    def __init__(
        self,
        node_uuid: UUID,
        signing_key: Ed25519PrivateKey,
        core_key: Ed25519PublicKey,
        rpc: JournalRpc,
    ) -> None:
        self._node_uuid, self._rpc = node_uuid, rpc
        self._signing_key, self._core_key = signing_key, core_key

    async def close(self) -> None:
        await self._rpc.close()

    async def exchange(
        self,
        payload: JournalAction,
        session_uuid: UUID,
        lease_epoch: int | None,
    ) -> JournalResult:
        now = int(time.time())
        request = JournalRequest(
            node_uuid=self._node_uuid,
            request_uuid=uuid4(),
            session_uuid=session_uuid,
            lease_epoch=lease_epoch,
            issued_at=now,
            expires_at=now + 10,
            payload=payload,
        )
        envelope = sign_request(request, self._signing_key)
        if len(envelope.model_dump_json().encode()) > MAX_REQUEST_BYTES:
            raise ValueError("Journal request exceeds its transport bound")
        try:
            async with asyncio.timeout(3):
                received = await self._rpc.exchange(envelope)
                reply = verify_reply(received, request, self._core_key, now=int(time.time()))
        except (TimeoutError, ValueError) as error:
            raise JournalUnavailable("Authenticated Resources journal unavailable") from error
        if reply.status_code == 409 and reply.result.error == "JOURNAL_CONFLICT":
            raise OperationConflict("Journal request conflicts with current execution state")
        if reply.status_code != 200 or reply.result.error is not None:
            logging.getLogger(__name__).error(
                "Resources journal rejected request status=%s code=%s",
                reply.status_code,
                reply.result.error,
            )
            raise JournalUnavailable("Journal request was not accepted")
        return reply.result
