"""Compatibility imports for existing callers; Teams owns the domain model."""

from .domain import Team, TeamMembership

__all__ = ["Team", "TeamMembership"]
