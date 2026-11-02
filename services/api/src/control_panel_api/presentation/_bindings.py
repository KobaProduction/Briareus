"""Typed instance references for existing API controller constructors."""


class _NativeControllerBinding[LoginT]:
    def __init__(self, login: LoginT, *, origin: str, host: str) -> None:
        self._login = login
        self._origin = origin
        self._host = host


class _ControllerServiceBinding[ServiceT, AuthorityT]:
    def __init__(self, service: ServiceT, authority: AuthorityT) -> None:
        self._service, self._authority = service, authority
