"""Bounded credential checks. No redirects, private IPs or provider payloads escape."""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import time
import jwt
from ipaddress import ip_address
from urllib.parse import urlsplit


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Public provider address required")
        # Connect to the validated numeric address; keep original hostname for TLS/SNI.
        family, kind, protocol, _, address = addresses[0]
        connection = socket.socket(family, kind, protocol)
        connection.settimeout(self.timeout)
        try:
            connection.connect(address)
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except BaseException:
            connection.close()
            raise


def check_connection(provider: str, base_url: str, token: str, auth_type: str,
                     external_id: str = "", ca_cert_pem: str = "") -> dict[str, object]:
    # Authentication algorithms ported from HTTP Bridge ProviderConnectionVerifier.
    github_path = "/user"
    if provider == "github" and auth_type == "github_app":
        now = int(time.time())
        token = jwt.encode({"iat": now - 60, "exp": now + 9 * 60, "iss": external_id},
                           token.replace("\\n", "\n"), algorithm="RS256")
        github_path = "/app"
    gitlab_header = {"PRIVATE-TOKEN": token} if auth_type == "private_token" else (
        {"JOB-TOKEN": token} if auth_type == "job_token" else {"Authorization": "Bearer " + token})
    endpoints = {
        "github": (github_path, {"Authorization": "Bearer " + token}),
        "gitlab": ("/api/v4/job" if auth_type == "job_token" else "/api/v4/user", gitlab_header),
        # Never enumerate other Coolify projects, global resources or secrets.
        "coolify": ("/api/v1/projects/3xshlpoghb9wcyhjgktlqzzp/naibrku1omovvmw5o0bcnp5c",
                    {"Authorization": "Bearer " + token}),
        "signoz": ("/api/v1/service_accounts/me", {"SIGNOZ-API-KEY": token}),
    }
    path, headers = endpoints[provider]
    target = urlsplit(base_url)
    context = ssl.create_default_context(cadata=ca_cert_pem.replace("\\n", "\n") if ca_cert_pem else None)
    connection = PublicHTTPSConnection(target.hostname, target.port or 443, timeout=5, context=context)
    try:
        connection.request("GET", target.path.rstrip("/") + path,
                           headers={**headers, "Accept": "application/json", "User-Agent": "Briareus"})
        response = connection.getresponse()
        raw = response.read(262145)
        if response.status in {401, 403}:
            return {"status": "denied", "message": "Провайдер отклонил ключ или доступ к выбранной среде"}
        if response.status != 200 or len(raw) > 262144:
            return {"status": "unavailable", "message": "Провайдер не подтвердил подключение"}
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Invalid provider response")
        # Do not return arbitrary provider fields, environment variables or response errors.
        identity = (value.get("slug") if auth_type == "github_app" else value.get("login")) if provider == "github" else (
            value.get("username") if provider == "gitlab" and auth_type != "job_token" else None)
        if (provider == "github" or provider == "gitlab" and auth_type != "job_token") and not isinstance(identity, str):
            raise ValueError("Provider identity missing")
        return {"status": "connected", "identity": identity[:128] if identity else None}
    finally:
        connection.close()
