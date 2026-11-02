"""Single-origin Panel, API, and upstream Rauthy OIDC reverse proxy.

Gateway only forwards fixed public namespaces; identity, JWT verification,
business permissions and authentication remain upstream responsibilities.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from gateway_runtime.thin_gateway import _raw_path as _raw_path
from gateway_runtime.thin_gateway import _upstream_unavailable

from ._api_contract import public_api_path, retired_auth_path
from ._call_journal import CallObserver, optional_observer
from ._mcp_admission import (
    McpAdmissionRejected,
    admission_error,
    authorize_connection,
    connection_target,
    parse_connection_admission,
)
from ._mcp_body import McpBodyRejected, read_mcp_body
from ._proxy_start import PendingProxyStart
from ._proxy_stream import ProxyStreamingResponse
from ._rauthy_admin_privacy import classify_rauthy_public_path
from .application.node_forwarding import NodeForwardingPort
from .domain.admission import ConnectionAdmission, HumanAdmission, McpAdmission
from .infrastructure.admission import TrustedGatewayDecisionPort
from .route_telemetry import RouteTelemetry
from .single_origin import MCP_ENDPOINTS, PUBLIC_HOST, SingleOriginGuard, unavailable_routes

_PANEL_UPSTREAM = "http://briareus-control-panel-ui:8080"
_API_UPSTREAM = "http://briareus-control-panel-api:8000"
_RAUTHY_UPSTREAM = "http://briareus-rauthy:8080"
# Routing is defined by the fixed public namespace, not by a Vite
# asset-extension/MIME registry. Nginx owns every Panel asset and SPA route.
_PANEL_PUBLIC_FILES = frozenset({"/", "/robots.txt", "/sitemap.xml"})
_HOP_HEADERS = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)
_PROXY_ASSERTIONS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-real-ip",
        "x-original-url",
        "x-rewrite-url",
    }
)
_TIMEOUT = httpx.Timeout(connect=3, read=60, write=30, pool=3)
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@dataclass(frozen=True, slots=True)
class PreparedMcpRequest:
    target: str
    headers: httpx.Headers
    observer: CallObserver | None


def mcp_context(request: Request) -> McpAdmission:
    admission = parse_connection_admission(request)
    values = request.headers.getlist("content-type")
    if len(values) != 1:
        raise McpAdmissionRejected("MCP_CONTENT_TYPE_INVALID", 415)
    media_type, separator, parameter = values[0].partition(";")
    if media_type.strip().lower() != "application/json" or (
        separator and parameter.strip().lower() != "charset=utf-8"
    ):
        raise McpAdmissionRejected("MCP_CONTENT_TYPE_INVALID", 415)
    return admission


def mcp_headers(request: Request, admission: McpAdmission) -> httpx.Headers:
    # Selectors are untrusted context. Every Hand repeats signed identity and
    # current owner admission before its effect.
    headers = httpx.Headers(
        {
            "Authorization": admission.bearer,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "X-Briareus-Project-UUID": str(admission.project_uuid),
        }
    )
    if isinstance(admission, ConnectionAdmission):
        headers["X-Briareus-Agent-Session-UUID"] = str(admission.agent_session_uuid)
        headers["X-Briareus-Grant-Revision"] = str(admission.grant_revision)
    protocol = request.headers.getlist("mcp-protocol-version")
    if len(protocol) == 1 and 0 < len(protocol[0]) <= 64:
        headers["Mcp-Protocol-Version"] = protocol[0]
    return headers


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """Public route template and its fixed internal service destination."""

    template: str
    target: Literal["panel-ui", "panel-api", "rauthy"]


# Runtime routing policy contains no principal, permissions or Identity paths.
_ROUTE_TABLE: tuple[RouteSpec, ...] = (
    RouteSpec("/", "panel-ui"),
    RouteSpec("/robots.txt", "panel-ui"),
    RouteSpec("/sitemap.xml", "panel-ui"),
    RouteSpec("/panel", "panel-ui"),
    RouteSpec("/panel/{path:path}", "panel-ui"),
    RouteSpec("/api", "panel-api"),
    RouteSpec("/api/{path:path}", "panel-api"),
    RouteSpec("/auth/v1", "rauthy"),
    RouteSpec("/auth/v1/{path:path}", "rauthy"),
)


def _connection_tokens(headers: list[tuple[bytes, bytes]]) -> set[str]:
    return {
        token.strip().casefold()
        for name, value in headers
        if name.lower() == b"connection"
        for token in value.decode("latin1").split(",")
    }


def _api_headers(request: Request) -> list[tuple[bytes, bytes]]:
    """Forward end-to-end headers, never browser-originated proxy identity."""
    incoming = request.scope.get("headers", [])
    connection_tokens = _connection_tokens(incoming)
    result: list[tuple[bytes, bytes]] = []
    for name, value in incoming:
        key = name.decode("ascii").casefold()
        if (
            key in _HOP_HEADERS
            or key in _PROXY_ASSERTIONS
            or key.startswith("x-forwarded-")
            or key in connection_tokens
        ):
            continue
        result.append((name, value))
    return result


def _api_declared_length(request: Request, *, rauthy: bool) -> bytes | None:
    """Preserve a single bounded original BFF length, never ambiguous framing."""
    if rauthy:
        # Rauthy provider routes retain their existing streaming semantics.
        return None
    lengths = request.headers.getlist("content-length")
    if not lengths:
        return None
    value = lengths[0]
    if (
        len(lengths) != 1
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 19
        or (len(value) > 1 and value.startswith("0"))
        or int(value) > 2**63 - 1
        or request.headers.getlist("transfer-encoding")
    ):
        raise ValueError("ambiguous Control Panel API HTTP framing")
    return value.encode("ascii")


def _upstream_headers(
    request: Request, *, rauthy: bool, declared_length: bytes | None
) -> list[tuple[bytes, bytes]]:
    """Separate outbound origin claims from incoming browser request headers."""
    headers = _api_headers(request)
    if declared_length is not None:
        headers.append((b"content-length", declared_length))
    # After SingleOriginGuard has independently checked exactly one
    # accepted public Host, give the PRIVATE API owner exactly one stable
    # canonical authority. HTTPX otherwise synthesizes the container DNS
    # destination Host, which the Backend native credentials BFF correctly
    # rejects. Never forward client Host / :443 / X-Forwarded assertions.
    headers.append((b"host", PUBLIC_HOST.encode("ascii")))
    if rauthy:
        # Rauthy owner also requires trusted Gateway external-origin hints.
        headers.extend(
            (
                (b"x-forwarded-host", PUBLIC_HOST.encode("ascii")),
                (b"x-forwarded-proto", b"https"),
            )
        )
    return headers


def api_path_rejection(request: Request, path: str) -> Response | None:
    decoded = request.scope.get("path")
    if retired_auth_path(raw_path=path, decoded_path=decoded, method=request.method):
        return JSONResponse(
            {"code": "AUTH_API_ROUTE_RETIRED"},
            status_code=404,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    if not public_api_path(raw_path=path, decoded_path=decoded, method=request.method):
        return JSONResponse(
            {"code": "API_ROUTE_NOT_PUBLIC"},
            status_code=404,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    return None


def rauthy_path_rejection(request: Request, path: str) -> Response | None:
    disposition = classify_rauthy_public_path(path, request.method)
    if disposition == "bad_path":
        return Response(status_code=400)
    if disposition == "private_admin":
        return JSONResponse(
            {"code": "RAUTHY_ADMIN_ROUTE_PRIVATE"},
            status_code=404,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    return None


def proxy_path(request: Request, *, rauthy: bool, panel_ui: bool) -> str | Response:
    path = _raw_path(request)
    if path is None:
        return Response(status_code=404)
    if panel_ui:
        if path == "/panel":
            return Response(
                status_code=308,
                headers={"Location": "/panel/", "Cache-Control": "no-store"},
            )
        decoded = request.scope.get("path")
        if (
            (path not in _PANEL_PUBLIC_FILES and not path.startswith("/panel/"))
            or not isinstance(decoded, str)
            or any(segment in {".", ".."} for segment in decoded.split("/"))
            or "//" in decoded
        ):
            return Response(status_code=404)
        return path
    prefix = "/auth/v1" if rauthy else "/api"
    if path != prefix and not path.startswith(prefix + "/"):
        return Response(status_code=404)
    rejection = (
        rauthy_path_rejection(request, path) if rauthy else api_path_rejection(request, path)
    )
    return path if rejection is None else rejection


def proxy_url(request: Request, path: str, *, rauthy: bool, panel_ui: bool) -> httpx.URL | None:
    query = request.scope.get("query_string", b"")
    if not isinstance(query, bytes):
        return None
    try:
        suffix = path + ("?" + query.decode("ascii") if query else "")
        origin = _PANEL_UPSTREAM if panel_ui else _RAUTHY_UPSTREAM if rauthy else _API_UPSTREAM
        target = httpx.URL(origin + suffix)
        expected = (
            ("briareus-control-panel-ui", 8080)
            if panel_ui
            else ("briareus-rauthy", 8080)
            if rauthy
            else ("briareus-control-panel-api", 8000)
        )
        return target if (target.host, target.port) == expected else None
    except (UnicodeDecodeError, ValueError, httpx.InvalidURL):
        return None


class ThinGateway:
    def __init__(
        self,
        private_decision: TrustedGatewayDecisionPort | None = None,
        *,
        node_router: NodeForwardingPort | None = None,
    ) -> None:
        self._private_decision = private_decision
        self._node_router = node_router
        self._client: httpx.AsyncClient | None = None
        self._slots = asyncio.Semaphore(64)
        self._draining = False
        self._open: set[httpx.Response] = set()
        self._streams: set[ProxyStreamingResponse] = set()
        self._pending: set[PendingProxyStart] = set()

    @asynccontextmanager
    async def lifespan(self, _app: Starlette) -> AsyncIterator[None]:
        self._draining = False
        from ._local_node_transport import local_node_transport

        transport = local_node_transport()

        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=24),
            follow_redirects=False,
            trust_env=False,
            mounts={"https://127.0.0.2:443": transport} if transport is not None else {},
        ) as client:
            self._client = client
            try:
                yield
            finally:
                self._draining = True
                self._client = None
                await self._drain_streams()

    async def _drain_streams(self) -> None:
        async def close_all() -> None:
            # Include requests still waiting for a client body or first
            # owner response; they have not become tracked streams yet.
            await asyncio.gather(
                *(pending.abort() for pending in tuple(self._pending)),
                return_exceptions=True,
            )
            # Each stream owns a three-second close deadline and frees its
            # own pool slot once. Parallel close avoids 64 sequential waits.
            await asyncio.gather(
                *(stream.aclose() for stream in tuple(self._streams)),
                return_exceptions=True,
            )

        cleanup = asyncio.create_task(close_all())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _send_upstream(
        self, client: httpx.AsyncClient, request: httpx.Request
    ) -> httpx.Response:
        if self._draining:
            raise httpx.ReadError("gateway is draining")
        pending = PendingProxyStart(client, request)
        self._pending.add(pending)
        try:
            return await pending.take_response()
        finally:
            self._pending.discard(pending)

    def _stream_response(
        self, upstream: httpx.Response, *, on_complete: CallObserver | None = None
    ) -> ProxyStreamingResponse:
        self._open.add(upstream)
        response = ProxyStreamingResponse(
            upstream,
            slots=self._slots,
            open_responses=self._open,
            tracked_streams=self._streams,
            on_complete=on_complete,
        )
        self._streams.add(response)
        return response

    _unavailable = staticmethod(_upstream_unavailable)

    async def static(self, request: Request) -> Response:
        """Route the whole bounded Panel namespace to its owning UI server.

        No mime sniff, response-body parsing, WASM/JS/CSS filename allowlist,
        noindex inspection, or fabricated UI reply belongs in Gateway.
        """
        return await self._proxy(request, rauthy=False, panel_ui=True)

    async def api(self, request: Request) -> Response:
        """Preserve the Admin API's unmodified public /api/* contract."""
        return await self._proxy(request, rauthy=False)

    async def oidc(self, request: Request) -> Response:
        """Forward only the real upstream Rauthy /auth/v1/* namespace."""
        return await self._proxy(request, rauthy=True)

    async def _prepare_mcp_request(
        self,
        request: Request,
        admission: McpAdmission,
        payload: bytes,
        *,
        began: float,
    ) -> PreparedMcpRequest:
        headers = mcp_headers(request, admission)
        target = connection_target(admission)
        if isinstance(admission, HumanAdmission) and self._node_router is None:
            raise McpAdmissionRejected("MCP_AUTHORIZATION_UNAVAILABLE", 503)
        call_observer: CallObserver | None = None
        if self._node_router is not None:
            protocol = request.headers.getlist("mcp-protocol-version")
            sessions = request.headers.getlist("mcp-session-id")
            if len(protocol) > 1 or len(sessions) > 1:
                raise ValueError("Ambiguous MCP framing context")
            async with asyncio.timeout(5):
                forwarding = await self._node_router.prepare(
                    admission,
                    payload,
                    protocol_version=protocol[0] if protocol else "",
                    mcp_session_id=sessions[0] if sessions else "",
                )
            target = forwarding.target
            headers.update(
                {
                    "x-briareus-node-permit": forwarding.permit,
                    "x-briareus-node-proof": forwarding.proof,
                    "x-briareus-node-signature": forwarding.signature,
                }
            )
            if forwarding.context:
                headers["x-briareus-invocation-context"] = forwarding.context
            call_observer = optional_observer(
                self._private_decision,
                payload,
                forwarding.permit,
                started=began,
            )
        return PreparedMcpRequest(target, headers, call_observer)

    async def _mcp_response(
        self,
        upstream: httpx.Response,
        call_observer: CallObserver | None,
    ) -> Response:
        # These include notification acknowledgments and independent Hand denials.
        if upstream.status_code not in {200, 202, 204, 400, 401, 403, 404, 409, 422, 429, 503}:
            rejected = self._stream_response(upstream, on_complete=call_observer)
            await rejected.aclose()
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        streamed = self._stream_response(upstream, on_complete=call_observer)
        if self._draining:
            await streamed.aclose()
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        # Only MCP framing metadata crosses the private Hand response boundary.
        streamed.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.decode("ascii").casefold()
            in {"content-type", "mcp-session-id", "mcp-protocol-version"}
        ] + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
        return streamed

    async def mcp(self, request: Request) -> Response:
        """Adapt transport around coarse connection and exact effect use cases."""
        began = time.monotonic()
        call_observer: CallObserver | None = None
        try:
            admission = mcp_context(request)
        except McpAdmissionRejected as exc:
            return admission_error(exc.code, exc.status_code)
        client = self._client
        if client is None or self._draining or self._private_decision is None:
            # Reject before reading caller bytes when no trusted owner exists.
            return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return admission_error("MCP_GATEWAY_BUSY", 503)
        try:
            payload = await read_mcp_body(request)
            blocked = (
                await authorize_connection(self._private_decision, admission)
                if isinstance(admission, ConnectionAdmission)
                else None
            )
            if blocked is not None:
                self._slots.release()
                return blocked
            prepared = await self._prepare_mcp_request(request, admission, payload, began=began)
            call_observer = prepared.observer
            outgoing = client.build_request(
                "POST",
                prepared.target,
                headers=prepared.headers,
                content=payload,
            )
            upstream = await self._send_upstream(client, outgoing)
        except asyncio.CancelledError:
            self._slots.release()
            if call_observer is not None:
                await call_observer(200, None, False)
            raise
        except (McpAdmissionRejected, McpBodyRejected) as error:
            self._slots.release()
            return admission_error(error.code, error.status_code)
        except (httpx.HTTPError, ValueError, TimeoutError):
            self._slots.release()
            if call_observer is not None:
                await call_observer(200, None, False)
            return admission_error("MCP_UPSTREAM_UNAVAILABLE", 503)
        except BaseException:
            self._slots.release()
            raise
        return await self._mcp_response(upstream, call_observer)

    async def _proxy(self, request: Request, *, rauthy: bool, panel_ui: bool = False) -> Response:
        selected = proxy_path(request, rauthy=rauthy, panel_ui=panel_ui)
        if isinstance(selected, Response):
            return selected
        target_url = proxy_url(request, selected, rauthy=rauthy, panel_ui=panel_ui)
        if target_url is None:
            return Response(status_code=400)
        # The native Backend expects exact Content-Length: 2 for "{}"
        # Init/PoW, but Rauthy must keep its established stream behavior.
        try:
            declared_length = _api_declared_length(request, rauthy=rauthy or panel_ui)
        except ValueError:
            return Response(status_code=400)
        client = self._client
        if client is None or self._draining:
            return self._unavailable()
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=3)
        except TimeoutError:
            return self._unavailable()
        try:
            headers = _upstream_headers(request, rauthy=rauthy, declared_length=declared_length)
            upstream_request = client.build_request(
                request.method,
                target_url,
                headers=headers,
                content=request.stream(),
            )
            upstream = await self._send_upstream(client, upstream_request)
        except asyncio.CancelledError:
            self._slots.release()
            raise
        except (httpx.HTTPError, ValueError, UnicodeError):
            self._slots.release()
            return self._unavailable()
        except BaseException:
            self._slots.release()
            raise
        streamed = self._stream_response(upstream)
        if self.is_draining():
            await streamed.aclose()
            return self._unavailable()
        # Preserve duplicate Set-Cookie and other end-to-end response headers.
        # ASGI streaming manages framing; do not send hop-by-hop headers.
        excluded = _HOP_HEADERS | _connection_tokens(upstream.headers.raw)
        streamed.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.decode("ascii").casefold() not in excluded
        ]
        return streamed

    def is_draining(self) -> bool:
        return self._draining


def build_app(
    *,
    private_decision: TrustedGatewayDecisionPort | None = None,
    node_router: NodeForwardingPort | None = None,
) -> Starlette:
    transport = ThinGateway(private_decision, node_router=node_router)
    handlers = {
        "panel-ui": transport.static,
        "panel-api": transport.api,
        "rauthy": transport.oidc,
    }
    return Starlette(
        routes=[
            *[
                Route(spec.template, handlers[spec.target], methods=_METHODS)
                for spec in _ROUTE_TABLE
            ],
            *[Route(path, transport.mcp, methods=["POST"]) for path in MCP_ENDPOINTS.values()],
            *unavailable_routes(),
        ],
        middleware=[Middleware(SingleOriginGuard), Middleware(RouteTelemetry)],
        lifespan=transport.lifespan,
    )
