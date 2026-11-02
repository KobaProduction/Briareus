"""Typed storage reference for existing Files Hand application use cases."""


class _StorageBinding[StorageT]:
    def __init__(self, storage: StorageT) -> None:
        self._storage = storage
