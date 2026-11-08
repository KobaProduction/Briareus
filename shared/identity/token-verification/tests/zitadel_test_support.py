from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from briareus_json_values import JsonObject, json_object
from briareus_oidc import OidcTokenSettings
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


class ZitadelTokenFixture:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "first"
        self.requests = 0
        self.discovery_requests = 0
        self.discovery_issuer: str | None = None
        self.jwks_path = "/oauth/v2/keys"
        self.jwks_uri: str | None = None
        self.introspection_requests = 0
        self.introspection_status = 200
        self.introspection_payload: JsonObject = {"active": False}
        self.introspection_authorization = ""
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/.well-known/openid-configuration":
                    fixture.discovery_requests += 1
                    content = json.dumps(
                        {
                            "issuer": fixture.discovery_issuer or fixture.settings.issuer_url,
                            "jwks_uri": fixture.jwks_uri
                            or fixture.settings.issuer_url + fixture.jwks_path,
                            "introspection_endpoint": fixture.settings.issuer_url + "/introspect",
                        }
                    ).encode()
                elif self.path == fixture.jwks_path:
                    fixture.requests += 1
                    key = json_object(RSAAlgorithm.to_jwk(fixture.key.public_key(), as_dict=True))
                    key.update({"kid": fixture.kid, "alg": "RS256", "use": "sig"})
                    content = json.dumps({"keys": [key]}).encode()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def do_POST(self) -> None:
                if self.path != "/introspect":
                    self.send_error(404)
                    return
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                fixture.introspection_requests += 1
                fixture.introspection_authorization = self.headers.get("Authorization", "")
                content = json.dumps(fixture.introspection_payload).encode()
                self.send_response(fixture.introspection_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format_string: str, *args: object) -> None:
                del format_string, args

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.settings = OidcTokenSettings(
            required_role="access",
            issuer_url=f"http://127.0.0.1:{self.server.server_port}",
            audience="briareus-project",
            roles_claim_path=("urn:zitadel:iam:org:project:briareus-project:roles",),
            roles_format="organization_grants",
            roles_organization_id="briareus-organization",
        )

    def token(self, overrides: JsonObject | None = None, *, omit: tuple[str, ...] = ()) -> str:
        now = int(time.time())
        payload: JsonObject = {
            "iss": self.settings.issuer_url,
            "sub": "user-1",
            "client_id": "registered-public-client",
            "aud": [self.settings.audience, "registered-public-client"],
            "exp": now + 3600,
            "iat": now - 1,
            "nbf": now - 1,
            "jti": "access-token-id",
            self.settings.roles_claim_path[0]: {
                "access": {self.settings.roles_organization_id: "example.test"},
            },
        }
        payload.update(overrides or {})
        for name in omit:
            payload.pop(name, None)
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": self.kid})

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
