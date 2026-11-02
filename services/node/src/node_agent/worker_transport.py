"""Gateway-only access to offline executors; no public or engine socket."""

import os
import re
import stat

import httpx

from node_protocol.browser_observation import OBSERVATION_PATH

from .runtime_profiles import SUPERVISOR_MODULES

WORKER_NAME = re.compile(r"briareus-[a-f0-9]{48}\Z", re.ASCII)


def _valid_request(request: httpx.Request, supervisor: bool, module: str) -> bool:
    return (
        request.method == "POST"
        and request.url.scheme == "http"
        and not request.url.username
        and not request.url.password
        and not request.url.fragment
        and (
            request.url.raw_path == b"/mcp"
            or (
                supervisor and module == "web" and request.url.raw_path == OBSERVATION_PATH.encode()
            )
        )
    )


class WorkerTransport(httpx.AsyncBaseTransport):
    def __init__(self, root: str = "/node-link/workers") -> None:
        self.root = root
        self.network = httpx.AsyncHTTPTransport()
        self.workers: dict[tuple[str, str], httpx.AsyncHTTPTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        name, separator, module = hostname.rpartition(".")
        supervisor = bool(separator and module in SUPERVISOR_MODULES)
        if not _valid_request(request, supervisor, module):
            raise httpx.ConnectError("Invalid executor request", request=request)
        if not supervisor:
            if (
                not WORKER_NAME.fullmatch(hostname)
                or request.url.port is None
                or not 1024 <= request.url.port <= 65535
            ):
                raise httpx.ConnectError("Unknown executor address", request=request)
            return await self.network.handle_async_request(request)
        if not WORKER_NAME.fullmatch(name) or request.url.port not in (None, 80):
            raise httpx.ConnectError("Invalid offline executor address", request=request)
        directory = os.path.join(self.root, name)
        path = os.path.join(directory, "mcp.sock")
        try:
            parent, socket = os.lstat(directory), os.lstat(path)
            if (
                not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) != 0o700
                or not stat.S_ISSOCK(socket.st_mode)
                or socket.st_uid != os.getuid()
                or stat.S_IMODE(socket.st_mode) != 0o600
            ):
                raise OSError("Private executor socket required")
        except OSError:
            raise httpx.ConnectError("Offline executor unavailable", request=request) from None
        key = (module, name)
        if key not in self.workers:
            if len(self.workers) >= 128:
                raise httpx.ConnectError(
                    "Offline executor transport capacity reached", request=request
                )
            self.workers[key] = httpx.AsyncHTTPTransport(
                uds=path, limits=httpx.Limits(max_connections=2, max_keepalive_connections=1)
            )
        return await self.workers[key].handle_async_request(request)

    async def aclose(self) -> None:
        await self.network.aclose()
        for transport in self.workers.values():
            await transport.aclose()
