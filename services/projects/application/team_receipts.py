"""Named team membership and ownership receipts for the local command ledger."""

from pydantic import BaseModel


class TeamMembershipChanged(BaseModel):
    team_id: str
    member_user_id: str
    team_version: int
    membership_version: int
    resource_revision: int
    active: bool


class TeamOwnerTransferred(BaseModel):
    team_id: str
    owner_user_id: str
    team_version: int
    resource_revision: int
