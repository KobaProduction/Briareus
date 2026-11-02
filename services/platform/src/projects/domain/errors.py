"""Platform domain failures shared by entity invariants and application outcomes."""


class _StatusCodeError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class ManagementError(_StatusCodeError):
    pass
