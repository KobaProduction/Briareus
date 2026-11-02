"""Private typed projection reference used by existing owner authority adapters."""


class _ProjectionBinding[ProjectionT]:
    def __init__(self, projection: ProjectionT) -> None:
        self._projection = projection
