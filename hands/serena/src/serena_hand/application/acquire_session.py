"""Fresh process leases cannot transfer prepared LSP state between identities."""

from collections.abc import Awaitable, Callable

type GrantLease = Callable[[tuple[str, str, int], int], Awaitable[bool]]


class AcquireSessionAuthority:
    def __init__(
        self,
        grant: GrantLease,
        ready: Callable[[], bool],
        now: Callable[[], float],
    ) -> None:
        self.grant = grant
        self.ready = ready
        self.now = now

    async def execute(
        self,
        identity: tuple[str, str, int],
        expires_at: int,
        *,
        existing_identity: bool,
    ) -> None:
        if not self.ready() or expires_at <= self.now():
            raise ValueError("Prepared actual Serena runtime and current authority required")
        preserved = await self.grant(identity, expires_at)
        if existing_identity and not preserved:
            raise ValueError("Serena identity changed; preparing a fresh isolated session")
