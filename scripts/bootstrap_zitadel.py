"""Provision only the isolated local Briareus ZITADEL instance; never print secrets."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ApiItem:
    identifier: str
    name: str


@dataclass(frozen=True)
class ApiReply:
    identifier: str = ""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    items: tuple[ApiItem, ...] = ()


@dataclass(frozen=True)
class BootstrapState:
    project_id: str = ""
    subject: str = ""
    app_id: str = ""
    client_id: str = ""


def text_field(payload: object, name: str) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get(name)
    return value if isinstance(value, str) else ""


def parse_reply(payload: object) -> ApiReply:
    if not isinstance(payload, dict):
        raise ValueError("provider response must be a JSON object")
    items: list[ApiItem] = []
    results = payload.get("result", [])
    if not isinstance(results, list):
        raise ValueError("provider search response is invalid")
    for item in results:
        identifier = text_field(item, "id") or text_field(item, "userId")
        items.append(ApiItem(identifier, text_field(item, "name") or text_field(item, "userName")))
    return ApiReply(
        text_field(payload, "id") or text_field(payload, "userId") or text_field(payload, "appId"),
        text_field(payload, "clientId"),
        text_field(payload, "clientSecret"),
        tuple(items),
    )


class LocalIdentityApi:
    def __init__(self, issuer: str, token: str) -> None:
        if issuer != "http://auth.bri.localhost:18081":
            raise ValueError("bootstrap is restricted to the isolated local identity issuer")
        self.issuer = issuer
        self.token = token

    def request(self, path: str, payload: object, *, method: str = "POST") -> ApiReply:
        request = urllib.request.Request(
            "http://127.0.0.1:18081" + path,
            data=json.dumps(payload).encode() if method != "GET" else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Host": urlsplit(self.issuer).netloc,
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return parse_reply(json.load(response))
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"local identity API rejected {method} {path}: HTTP {error.code}"
            ) from None

    def find(self, path: str, query_name: str, name: str) -> str:
        query = {
            "queries": [
                {
                    query_name: {
                        "name" if query_name == "nameQuery" else "userName": name,
                        "method": "TEXT_QUERY_METHOD_EQUALS",
                    }
                }
            ]
        }
        reply = self.request(path, query)
        if len(reply.items) > 1:
            raise RuntimeError("ambiguous existing local identity resource; refusing replacement")
        return reply.items[0].identifier if reply.items else ""


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def load_state(path: Path) -> BootstrapState:
    if not path.exists():
        return BootstrapState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BootstrapState(
        *(
            text_field(payload, name)
            for name in (
                "project_id",
                "subject",
                "app_id",
                "client_id",
            )
        )
    )


def save_state(path: Path, state: BootstrapState) -> None:
    write_private(
        path,
        json.dumps(
            {
                "project_id": state.project_id,
                "subject": state.subject,
                "app_id": state.app_id,
                "client_id": state.client_id,
            },
            indent=2,
        ),
    )


def provision_project(api: LocalIdentityApi, state: BootstrapState) -> str:
    if state.project_id:
        api.request("/management/v1/projects/" + state.project_id, None, method="GET")
        return state.project_id
    found = api.find("/management/v1/projects/_search", "nameQuery", "BRI Local")
    return found or api.request("/management/v1/projects", {"name": "BRI Local"}).identifier


def provision_subject(api: LocalIdentityApi, state: BootstrapState, directory: Path) -> str:
    if state.subject:
        api.request("/management/v1/users/" + state.subject, None, method="GET")
        return state.subject
    found = api.find("/management/v1/users/_search", "userNameQuery", "bri-local-admin")
    if found:
        return found
    password_file = directory / "secrets" / "initial-admin-password"
    if not password_file.exists():
        write_private(password_file, "Bri1!" + secrets.token_urlsafe(24))
    reply = api.request(
        "/v2/users/human",
        {
            "username": "bri-local-admin",
            "profile": {"givenName": "BRI", "familyName": "Local Admin"},
            "email": {"email": "admin@bri.localhost", "isVerified": True},
            "password": {
                "password": password_file.read_text(encoding="utf-8"),
                "changeRequired": False,
            },
        },
    )
    if not reply.identifier:
        raise RuntimeError("ZITADEL did not return a subject for the new local human")
    return reply.identifier


def provision_client(
    api: LocalIdentityApi, state: BootstrapState, directory: Path, public_url: str
) -> BootstrapState:
    secret_file = directory / "secrets" / "zitadel-client-secret"
    if state.client_id and state.app_id and secret_file.exists():
        api.request(
            f"/management/v1/projects/{state.project_id}/apps/{state.app_id}", None, method="GET"
        )
        return state
    path = f"/management/v1/projects/{state.project_id}/apps"
    if api.find(path + "/_search", "nameQuery", "BRI Local Web"):
        raise RuntimeError(
            "local OIDC client exists but its saved secret/state is missing; refusing rotation"
        )
    reply = api.request(
        path + "/oidc",
        {
            "name": "BRI Local Web",
            "redirectUris": [public_url + "/auth/callback", public_url + "/api/auth/callback"],
            "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
            "grantTypes": ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"],
            "appType": "OIDC_APP_TYPE_WEB",
            "authMethodType": "OIDC_AUTH_METHOD_TYPE_BASIC",
            "postLogoutRedirectUris": [public_url + "/admin/"],
            "version": "OIDC_VERSION_1_0",
            "devMode": True,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
            "idTokenUserinfoAssertion": True,
        },
    )
    if not reply.identifier or not reply.client_id or not reply.client_secret:
        raise RuntimeError("ZITADEL did not return complete local OIDC credentials")
    write_private(secret_file, reply.client_secret)
    return BootstrapState(state.project_id, state.subject, reply.identifier, reply.client_id)


def bootstrap(directory: Path, issuer: str, public_url: str) -> None:
    state_path = directory / "identity-state.json"
    token_path = directory / "zitadel-bootstrap" / "admin.pat"
    if not token_path.exists():
        raise RuntimeError("start isolated local ZITADEL first; bootstrap PAT is not available")
    api = LocalIdentityApi(issuer, token_path.read_text(encoding="utf-8").strip())
    state = load_state(state_path)
    state = BootstrapState(
        provision_project(api, state), state.subject, state.app_id, state.client_id
    )
    save_state(state_path, state)
    state = BootstrapState(
        state.project_id, provision_subject(api, state, directory), state.app_id, state.client_id
    )
    save_state(state_path, state)
    state = provision_client(api, state, directory, public_url)
    save_state(state_path, state)
    write_private(
        directory / "identity.env",
        "\n".join(
            (
                "ZITADEL_ISSUER_URL=" + issuer,
                "ZITADEL_CLIENT_ID=" + state.client_id,
                "ZITADEL_CLIENT_SECRET_FILE=/run/secrets/zitadel-client-secret",
                "ZITADEL_ALLOWED_SUBJECTS=" + state.subject,
                "ZITADEL_ALLOW_LOCAL_HTTP=true",
                "MCP_PUBLIC_BASE_URL=" + public_url,
                "MCP_OAUTH_JWT_SIGNING_KEY_FILE=/run/secrets/mcp-oauth-signing-key",
                "MCP_OAUTH_STATE_DIRECTORY=/var/lib/bri/oauth",
                "CONTROL_PANEL_PUBLIC_BASE_URL=" + public_url,
                "",
            )
        ),
    )
    print("Local ZITADEL project, explicit human subject and OIDC client are provisioned.")
    print("Credentials remain in the ignored local state directory; no secret values were printed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", default="http://auth.bri.localhost:18081")
    parser.add_argument("--state-dir", type=Path, default=Path(".local/bri-v1"))
    parser.add_argument("--public-url", default="http://localhost:18080")
    args = parser.parse_args()
    if args.public_url != "http://localhost:18080":
        raise SystemExit("bootstrap supports only the isolated local Briareus origin")
    try:
        bootstrap(args.state_dir.resolve(), args.issuer, args.public_url)
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
