"""HTTPS adapter limited to one already-approved application's Watch Paths."""

from __future__ import annotations

import json
from email.message import Message
from http.client import HTTPResponse
from typing import IO, Literal, override
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from watch_sync_domain import COOLIFY_ORIGIN, ApprovedWatchTarget, SavedWatchMetadata, SyncError
from watch_sync_sources import decode_metadata


class _NoRedirect(HTTPRedirectHandler):
    @override
    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: Message, newurl: str
    ) -> None:
        raise SyncError("Coolify redirect rejected; approved origin and resource must remain exact")


class CoolifyWatchConfiguration:
    def __init__(self, target: ApprovedWatchTarget, token: str) -> None:
        if not token:
            raise SyncError("a scoped Coolify token is required")
        self._url = f"{COOLIFY_ORIGIN}/api/v1/applications/{target.identity.uuid}"
        self._token = token
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, method: Literal["GET", "PATCH"], body: bytes | None = None) -> bytes:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(  # noqa: S310 -- fixed HTTPS origin and pre-approved UUID, redirects denied
            self._url, data=body, headers=headers, method=method
        )
        try:
            # The origin and UUID were fixed before credentials became available.
            with self._opener.open(request, timeout=15) as response:
                if not isinstance(response, HTTPResponse):
                    raise SyncError("unexpected Coolify HTTPS response")
                raw = response.read(131073)
        except HTTPError as error:
            raise SyncError(f"Coolify returned HTTP {error.code}; response body withheld") from None
        except (URLError, TimeoutError, OSError):
            raise SyncError(
                "Coolify transport failed; request outcome may require inspection"
            ) from None
        if len(raw) > 131072:
            raise SyncError("Coolify application metadata exceeded the response bound")
        return raw

    def read(self) -> SavedWatchMetadata:
        try:
            return decode_metadata(self._request("GET"))
        except (ValueError, UnicodeError):
            raise SyncError("Coolify application metadata is not valid JSON") from None

    def replace_watch_paths(self, value: str) -> None:
        self._request("PATCH", json.dumps({"watch_paths": value}).encode("utf-8"))
