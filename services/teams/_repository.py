"""Compatibility imports for the caller-owned transaction adapter."""

from .infrastructure.repository import TeamRepository, to_team

__all__ = ["TeamRepository", "to_team"]
