"""Existing flat Git tool wire schema for named Node receipts and legacy adapters."""

import json

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, TypeAdapter

from hand_runtime.provider_results import provider_result
from svc_hand.domain.local_git import CheckoutReceipt, LocalGitAuthorization, LocalGitPush

_NODE_RECEIPT: TypeAdapter[LocalGitAuthorization | LocalGitPush | CheckoutReceipt] = TypeAdapter(
    LocalGitAuthorization | LocalGitPush | CheckoutReceipt
)


def local_git_result(
    receipt: LocalGitAuthorization | LocalGitPush | CheckoutReceipt | BaseModel,
) -> CallToolResult:
    if isinstance(receipt, BaseModel):
        return provider_result(receipt)
    # The three existing domain receipts own every output field. Preserve the
    # checkout protocol's omitted ref, without dropping an explicit null branch.
    omitted = {"ref"} if isinstance(receipt, CheckoutReceipt) and receipt.ref is None else None
    payload = _NODE_RECEIPT.dump_python(receipt, mode="json", exclude=omitted)
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload, ensure_ascii=True, allow_nan=False))
        ],
        structured_content=payload,
    )
