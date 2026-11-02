"""Exact analysis command headers with SDK-owned tool arguments."""

import json

from pydantic import UUID4, StrictInt

from .private_call import PrivateToolCall


class AnalysisCommand(PrivateToolCall):
    id: UUID4
    expires_at: StrictInt

    def encode(self) -> bytes:
        payload = (
            json.dumps(
                {
                    "id": str(self.id),
                    "tool": self.call.name,
                    "arguments": self.call.arguments or {},
                    "expires_at": self.expires_at,
                },
                allow_nan=False,
            ).encode()
            + b"\n"
        )
        if len(payload) > 32768:
            raise ValueError("Bounded analysis command required")
        return payload
