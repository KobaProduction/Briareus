"""Approval guidance extends the authoritative Access request observation."""

from common.access_contracts import AccessRequestView


class AccessApprovalReceipt(AccessRequestView):
    instructions: str

    @classmethod
    def pending(
        cls, request: AccessRequestView, session_uid: str, instructions: str
    ) -> "AccessApprovalReceipt":
        # The MCP surface exposes its opaque public session UID, not the private row ID.
        return cls(
            id=request.id,
            session_id=session_uid,
            kind=request.kind,
            status=request.status,
            requested_access_level=request.requested_access_level,
            requested_account_scope=request.requested_account_scope,
            requested_account_ids=request.requested_account_ids,
            requested_expires_at=request.requested_expires_at,
            instructions=instructions,
        )
