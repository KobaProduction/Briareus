"""Store an existing application port under its unchanged public reference."""


class _RuntimeBinding[RuntimeT]:
    def __init__(self, runtime: RuntimeT) -> None:
        self.runtime = runtime
