"""Private constructor storage shared by the Control Panel infrastructure adapters."""

from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse

from control_panel_api._oidc_membership import CurrentPlatformContext
from service_runtime._reference_bindings import _PeerBinding as _PeerBinding

if TYPE_CHECKING:
    from control_panel_api.application.realtime_publisher import EventPublisher


class _PublisherBinding:
    def __init__(self, publisher: "EventPublisher") -> None:
        self._publisher = publisher


class _HttpAuthorityBinding:
    def __init__(self, request: Request, current: CurrentPlatformContext) -> None:
        self._request, self._current = request, current
        self.rejection: JSONResponse | None = None
