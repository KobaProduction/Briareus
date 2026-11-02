"""Compatibility imports preserving registered table and ORM class identities."""

from .infrastructure.persistence import TeamMembershipRow, TeamRow

__all__ = ["TeamMembershipRow", "TeamRow"]
