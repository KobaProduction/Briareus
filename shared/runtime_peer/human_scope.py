"""Resource-owner confirmed tools available to the current human project user."""

from pydantic import BaseModel, ConfigDict


class ScopeResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    id: str


class ScopeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hand: str
    tool: str
    action: str
    resource: ScopeResource


class HumanScopeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[ScopeItem, ...]
