"""Private initialization shared by the existing code-bearing exception classes."""


class _CodeError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
