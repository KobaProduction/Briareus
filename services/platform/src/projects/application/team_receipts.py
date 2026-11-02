"""Named team membership and ownership receipts for the local command ledger."""

from pydantic import BaseModel


class TeamMembershipChanged(BaseModel):
    team_id: str
    member_user_id: str
    state: str
    resource_revision: int
    active: bool


class TeamOwnerTransferred(BaseModel):
    team_id: str
    owner_user_id: str
    state: str
    resource_revision: int
