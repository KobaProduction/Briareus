from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from briareus_json_values import JsonObject, json_object
from briareus_zitadel_tokens import ZitadelTokenSettings
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


class ZitadelTokenFixture:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "first"
        self.requests = 0
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fixture.requests += 1
                if self.path != "/oauth/v2/keys":
                    self.send_error(404)
                    return
                key = json_object(RSAAlgorithm.to_jwk(fixture.key.public_key(), as_dict=True))
                key.update({"kid": fixture.kid, "alg": "RS256", "use": "sig"})
                content = json.dumps({"keys": [key]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format_string: str, *args: object) -> None:
                del format_string, args

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.settings = ZitadelTokenSettings(
            issuer_url=f"http://127.0.0.1:{self.server.server_port}",
            project_id="briareus-project",
            organization_id="briareus-organization",
        )

    def token(self, overrides: JsonObject | None = None, *, omit: tuple[str, ...] = ()) -> str:
        now = int(time.time())
        payload: JsonObject = {
            "iss": self.settings.issuer_url,
            "sub": "user-1",
            "azp": "registered-public-client",
            "aud": [self.settings.project_id, "registered-public-client"],
            "exp": now + 3600,
            "iat": now - 1,
            "nbf": now - 1,
            "jti": "access-token-id",
            self.settings.roles_claim: {
                "access": {self.settings.organization_id: "example.test"},
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
