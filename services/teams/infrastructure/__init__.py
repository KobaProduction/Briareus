"""Teams persistence adapters; domain code never imports this package."""

from .management import bind_team_management

__all__ = ["bind_team_management"]
