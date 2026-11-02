"""Teams failures independent of transport status and other service errors."""


class TeamError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class TeamAccessDenied(TeamError):
    """The actor cannot access or administer this Team."""


class TeamConflict(TeamError):
    """The current Team state conflicts with the requested transition."""


class TeamResourceMissing(TeamError):
    """A required User or membership is unavailable."""


class TeamInvalidInput(TeamError):
    """The supplied Team name is invalid."""
