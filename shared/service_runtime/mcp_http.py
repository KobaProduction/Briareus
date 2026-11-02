"""MCP HTTP transport clients with explicit response-read timeout semantics."""

import httpx2


def mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
    follow_redirects: bool = False,
) -> httpx2.AsyncClient:
    # MCP follows redirects within the endpoint origin in its stream adapter.
    # Automatic httpx redirects would bypass that check, including for POSTs.
    del follow_redirects
    configured = timeout if timeout is not None else httpx2.Timeout(30.0, read=None)
    return httpx2.AsyncClient(
        headers=headers,
        auth=auth,
        timeout=configured,
        follow_redirects=False,
    )
