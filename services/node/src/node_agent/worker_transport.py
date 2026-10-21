"""Gateway-only access to offline executors; no public or engine socket."""
import os
import re
import stat

import httpx
from .runtime_profiles import SUPERVISOR_MODULES

WORKER_NAME = re.compile(r"briareus-[a-f0-9]{48}\Z", re.ASCII)


class WorkerTransport(httpx.AsyncBaseTransport):
    def __init__(self, root="/node-link/workers"):
        self.root = root
        self.network = httpx.AsyncHTTPTransport()
        self.workers = {}

    async def handle_async_request(self, request):
        hostname = request.url.host
        name, separator, module = hostname.rpartition(".")
        supervisor = separator and module in SUPERVISOR_MODULES
        if (request.method != "POST" or request.url.scheme != "http" or request.url.raw_path != b"/mcp"
            or request.url.username or request.url.password or request.url.fragment):
            raise httpx.ConnectError("Invalid executor request", request=request)
        if not supervisor:
            if not WORKER_NAME.fullmatch(hostname) or request.url.port is None or not 1024 <= request.url.port <= 65535:
                raise httpx.ConnectError("Unknown executor address", request=request)
            return await self.network.handle_async_request(request)
        if not WORKER_NAME.fullmatch(name) or request.url.port not in (None, 80):
            raise httpx.ConnectError("Invalid offline executor address", request=request)
        directory = os.path.join(self.root, name)
        path = os.path.join(directory, "mcp.sock")
        try:
            parent, socket = os.lstat(directory), os.lstat(path)
            if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) != 0o700 or not stat.S_ISSOCK(socket.st_mode)
                or socket.st_uid != os.getuid() or stat.S_IMODE(socket.st_mode) != 0o600):
                raise OSError("Private executor socket required")
        except OSError:
            raise httpx.ConnectError("Offline executor unavailable", request=request) from None
        key = (module, name)
        if key not in self.workers:
            if len(self.workers) >= 128:
                raise httpx.ConnectError("Offline executor transport capacity reached", request=request)
            self.workers[key] = httpx.AsyncHTTPTransport(uds=path,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=1))
        return await self.workers[key].handle_async_request(request)

    async def aclose(self):
        await self.network.aclose()
        for transport in self.workers.values():
            await transport.aclose()
