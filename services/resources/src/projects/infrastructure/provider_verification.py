"""Public-address pinned HTTPS probes; provider payloads never leave this adapter."""

import asyncio
import http.client
import json
import socket
import ssl
import time
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit

import jwt

from projects.domain.provider_connections import ProviderCheck, ProviderProbe


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, *, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._provider_context = context

    def connect(self) -> None:
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Public provider address required")
        family, kind, protocol, _, address = addresses[0]
        connection = socket.socket(family, kind, protocol)
        connection.settimeout(self.timeout)
        try:
            connection.connect(address)
            self.sock = self._provider_context.wrap_socket(connection, server_hostname=self.host)
        except BaseException:
            connection.close()
            raise


@dataclass(frozen=True)
class ProviderRequest:
    path: str
    header: str
    credential: str = field(repr=False)


def provider_request(probe: ProviderProbe) -> ProviderRequest:
    if probe.provider == "github":
        if probe.auth_type == "github_app":
            now = int(time.time())
            token = jwt.encode(
                {"iat": now - 60, "exp": now + 9 * 60, "iss": probe.external_id},
                probe.token.replace("\\n", "\n"),
                algorithm="RS256",
            )
            return ProviderRequest("/app", "Authorization", "Bearer " + token)
        return ProviderRequest("/user", "Authorization", "Bearer " + probe.token)
    if probe.provider == "gitlab":
        return gitlab_request(probe)
    if probe.provider == "coolify":
        return ProviderRequest(
            "/api/v1/projects/3xshlpoghb9wcyhjgktlqzzp/naibrku1omovvmw5o0bcnp5c",
            "Authorization",
            "Bearer " + probe.token,
        )
    if probe.provider == "signoz":
        return ProviderRequest("/api/v1/service_accounts/me", "SIGNOZ-API-KEY", probe.token)
    raise ValueError("Unsupported provider")


def gitlab_request(probe: ProviderProbe) -> ProviderRequest:
    if probe.auth_type == "job_token":
        return ProviderRequest("/api/v4/job", "JOB-TOKEN", probe.token)
    header, token = (
        ("PRIVATE-TOKEN", probe.token)
        if probe.auth_type == "private_token"
        else ("Authorization", "Bearer " + probe.token)
    )
    return ProviderRequest("/api/v4/user", header, token)


def provider_identity(probe: ProviderProbe, raw: bytes) -> str | None:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid provider response")
    if probe.provider == "github":
        selected = value.get("slug" if probe.auth_type == "github_app" else "login")
    elif probe.provider == "gitlab" and probe.auth_type != "job_token":
        selected = value.get("username")
    else:
        return None
    if not isinstance(selected, str):
        raise ValueError("Provider identity missing")
    return selected[:128] if selected else None


def verify_provider(probe: ProviderProbe) -> ProviderCheck:
    request = provider_request(probe)
    target = urlsplit(probe.base_url)
    if target.hostname is None:
        raise ValueError("Provider hostname required")
    context = ssl.create_default_context(
        cadata=probe.ca_cert_pem.replace("\\n", "\n") if probe.ca_cert_pem else None
    )
    connection = PublicHTTPSConnection(
        target.hostname, target.port or 443, timeout=5, context=context
    )
    try:
        connection.request(
            "GET",
            target.path.rstrip("/") + request.path,
            headers={
                request.header: request.credential,
                "Accept": "application/json",
                "User-Agent": "Briareus",
            },
        )
        response = connection.getresponse()
        raw = response.read(262145)
        if response.status in {401, 403}:
            return ProviderCheck("denied", "Провайдер отклонил ключ или доступ к выбранной среде")
        if response.status != 200 or len(raw) > 262144:
            return ProviderCheck.unavailable()
        return ProviderCheck("connected", identity=provider_identity(probe, raw))
    finally:
        connection.close()


class HTTPSProviderVerifier:
    async def verify(self, probe: ProviderProbe) -> ProviderCheck:
        try:
            async with asyncio.timeout(7):
                return await asyncio.to_thread(verify_provider, probe)
        except Exception as exc:
            raise ValueError("Provider verification unavailable") from exc
