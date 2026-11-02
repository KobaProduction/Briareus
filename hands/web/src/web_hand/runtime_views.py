"""Typed private browser replies and the durable per-operation ledger record."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from runtime_peer.browser_receipts import (
    BrowserCallReceipt as BrowserCallReceipt,
)
from runtime_peer.browser_receipts import (
    BrowserInspectionResult as BrowserInspectionResult,
)


class RuntimeLive(BaseModel):
    state: Literal["live"] = "live"
    mode: Literal["private-owner-runtime"] = "private-owner-runtime"


class RuntimeInspection(BaseModel):
    project_uuid: UUID
    isolated: bool
    resource_id: str
    resource_revision: int
    tools: list[str]


class RuntimeOperationLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fingerprint: str = Field(min_length=64, max_length=64)
    reply: BrowserCallReceipt | None = None
