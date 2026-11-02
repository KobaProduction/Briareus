"""Existing Access resource-catalogue replies shared by the producer and BFF decoder.

These transport facts do not grant access or verify current owner authority.
Each HTTP adapter retains its existing optional-field serialization policy.
"""

from pydantic import BaseModel


class RuntimeResource(BaseModel):
    hand: str
    kind: str
    id: str


class RuntimeResourceSelector(BaseModel):
    kind: str
    id: str


class RuntimeResourceItem(BaseModel):
    hand: str
    tool: str
    action: str
    resource: RuntimeResourceSelector


class RuntimeResources(BaseModel):
    items: tuple[RuntimeResourceItem, ...]
    expires_at: str
    resource: RuntimeResource | None = None
    catalogue_state: str | None = None
