"""Provider HTTPS transport through the Node's public-only egress boundary."""
import http.client
import os
import ssl
from urllib.parse import urlsplit


def provider_connection(base_url, *, verify_tls=True, ca_cert_pem=None, timeout=30):
    target = urlsplit(base_url)
    proxy = urlsplit(os.environ.get("HTTPS_PROXY", ""))
    if (target.scheme != "https" or not target.hostname or target.port not in (None, 443)
        or target.username or target.password or target.fragment or target.query
        or not verify_tls or proxy.scheme != "http" or proxy.hostname != "module-egress"
        or proxy.port != 8080 or proxy.username or proxy.password or proxy.path not in ("", "/")):
        raise ValueError("Approved HTTPS provider and public-only Node egress proxy required")
    context = ssl.create_default_context(cadata=ca_cert_pem.replace("\\n", "\n") if ca_cert_pem else None)
    from hand_runtime.runtime_policy import runtime_policy
    effect_timeout=runtime_policy().execution_timeout_seconds
    class ProviderConnection(http.client.HTTPSConnection):
        def connect(self):
            # TCP/TLS startup remains bounded independently of MCP execution.
            self.timeout=10
            super().connect()
            self.sock.settimeout(effect_timeout)
            self.timeout=effect_timeout
    connection = ProviderConnection(proxy.hostname, proxy.port, timeout=10, context=context)
    connection.set_tunnel(target.hostname, 443)
    return connection
