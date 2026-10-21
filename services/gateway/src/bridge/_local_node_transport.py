"""Explicit local Docker dial mapping, preserving TLS identity and HTTP authority."""
import os
import ssl

import httpx


class LocalNodeTransport(httpx.AsyncBaseTransport):
    def __init__(self, ca_file):
        context=ssl.create_default_context(cafile=ca_file)
        self.inner=httpx.AsyncHTTPTransport(verify=context,retries=0,trust_env=False)

    async def handle_async_request(self, request):
        if request.url.scheme!="https" or request.url.host!="127.0.0.2" or request.url.port not in {None,443}:
            raise ValueError("Exact local node TLS origin required")
        mapped=httpx.Request(request.method,request.url.copy_with(host="local-node-tls"),
            headers=request.headers,stream=request.stream,
            extensions={**request.extensions,"sni_hostname":"127.0.0.2"})
        return await self.inner.handle_async_request(mapped)

    async def aclose(self):
        await self.inner.aclose()


def local_node_mounts():
    if not os.environ.get("BRIAREUS_LOCAL_NODE_DIAL"):
        return {}
    if (os.environ.get("BRIAREUS_LOCAL_TESTING")!="1"
        or os.environ["BRIAREUS_LOCAL_NODE_DIAL"]!="local-node-tls:443"):
        raise ValueError("Only the explicit local node adapter may override dialing")
    return {"https://127.0.0.2:443":LocalNodeTransport(os.environ["BRIAREUS_NODE_CA_FILE"])}
