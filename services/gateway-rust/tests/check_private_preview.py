"""Private Gateway preview admission/packaging; no Docker or live credentials."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import unittest
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[3]
PREVIEW = ROOT / "services/gateway-rust"
BINARY = ROOT / "services/gateway-rust/target/debug/briareus-gateway-rust"


class PreviewIsolationContracts(unittest.TestCase):
    def test_preview_has_no_public_ingress_or_existing_gateway_alias(self) -> None:
        model = yaml.safe_load((PREVIEW / "docker-compose.preview.yaml").read_text())
        self.assertEqual(set(model["services"]), {"gateway-preview"})
        service = model["services"]["gateway-preview"]
        for field in ("ports", "expose", "labels", "container_name", "hostname"):
            self.assertNotIn(field, service)
        self.assertEqual(service["networks"], ["briareus-private"])
        self.assertEqual(set(model["networks"]), {"briareus-private"})
        self.assertTrue(model["networks"]["briareus-private"]["external"])
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertNotIn("root", service["user"])
        self.assertEqual(service["environment"]["GATEWAY_PRIVATE_PREVIEW"], "true")
        self.assertNotIn("RUST_GATEWAY_SHADOW_ONLY", service["environment"])
        for name in ("OIDC_ISSUER_URL", "OIDC_AUDIENCE", "BRIAREUS_NODE_ID", "VALKEY_PASSWORD"):
            self.assertIn(":?", service["environment"][name])

    def test_preview_does_not_change_live_gateway_catalog_and_watchers(self) -> None:
        import json

        catalog = json.loads((ROOT / "deploy/services.json").read_text())
        gateway = next(s for s in catalog["services"] if s["name"] == "gateway")
        self.assertEqual(gateway["directory"], "services/gateway")
        self.assertNotIn("services/gateway-rust/**", gateway["watch_paths"])
        self.assertNotIn("shared/service-discovery/**", gateway["watch_paths"])
        self.assertFalse(any(s["name"] == "gateway-preview" for s in catalog["services"]))

    def test_preview_docker_context_is_only_native_source(self) -> None:
        recipe = (PREVIEW / "Dockerfile.preview").read_text()
        ignored = (PREVIEW / "Dockerfile.preview.dockerignore").read_text()
        self.assertIn("USER 10001:10001", recipe)
        self.assertIn("cargo build --release --locked", recipe)
        self.assertIn("**/target/**", ignored)
        for line in recipe.splitlines():
            if not line.startswith("COPY ") or "--from=" in line:
                continue
            for source in line.split()[1:-1]:
                self.assertTrue((ROOT / source).exists(), source)
                self.assertNotIn("services/gateway/", source)

    def test_private_preview_starts_with_synthetic_authorities_and_no_fixture_routing(self) -> None:
        if not BINARY.is_file():
            raise RuntimeError("Build the Rust Gateway binary before mode acceptance tests")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {
            **os.environ,
            "GATEWAY_PRIVATE_PREVIEW": "true",
            "BIND_HOST": "0.0.0.0",
            "PORT": str(port),
            "BRIAREUS_NODE_ID": "test",
            "CONTROL_PANEL_URL": "http://127.0.0.1:1",
            "CONTROL_PANEL_UI_URL": "http://127.0.0.1:1",
            "MCP_PUBLIC_BASE_URL": "https://briareus.example",
            "OIDC_ISSUER_URL": "http://127.0.0.1:1",
            "OIDC_AUDIENCE": "synthetic-project",
            "OIDC_TOKEN_VERIFICATION": "jwt",
            "OIDC_JWT_ALGORITHMS": "RS256",
            "OIDC_ROLES_CLAIM_PATH": '["roles"]',
            "OIDC_ROLES_FORMAT": "list",
            "VALKEY_PASSWORD": "synthetic-valkey-password",
            "VALKEY_URL": "redis://127.0.0.1:1/0",
            "DEPLOYMENT_ENVIRONMENT": "test",
        }
        env.pop("RUST_GATEWAY_SHADOW_ONLY", None)
        env.pop("GATEWAY_SHADOW_TARGETS_JSON", None)
        with subprocess.Popen(
            [str(BINARY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        ) as process:
            try:
                with httpx.Client(timeout=0.4, trust_env=False) as client:
                    for _ in range(75):
                        if process.poll() is not None:
                            raise AssertionError("Preview exited before readiness")
                        try:
                            health = client.get(f"http://127.0.0.1:{port}/health")
                            if health.status_code == 200:
                                self.assertEqual(health.json()["node"], "test")
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.04)
                    else:
                        self.fail("Private preview did not become ready")
                    # Authorization cannot be bypassed via a discovered route.
                    unauthorized = client.post(
                        f"http://127.0.0.1:{port}/observability/signoz/mcp",
                        headers={"Accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    )
                    self.assertNotEqual(unauthorized.status_code, 200)
            finally:
                process.terminate()
                process.communicate(timeout=5)

    def test_preview_rejects_shadow_target_override(self) -> None:
        if not BINARY.is_file():
            raise RuntimeError("Build the Rust Gateway binary before mode acceptance tests")
        env = {
            "GATEWAY_PRIVATE_PREVIEW": "true",
            "BIND_HOST": "0.0.0.0",
            "VALKEY_PASSWORD": "synthetic-valkey-password",
            "OIDC_ISSUER_URL": "http://127.0.0.1:1",
            "GATEWAY_SHADOW_TARGETS_JSON": "{}",
        }
        result = subprocess.run([str(BINARY)], env=env, capture_output=True, timeout=5, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"forbids shadow fixture target overrides", result.stderr)

    def test_process_rejects_unsafe_preview_modes_before_network_access(self) -> None:
        if not BINARY.is_file():
            raise RuntimeError("Build the Rust Gateway binary before mode acceptance tests")
        base = {
            "BIND_HOST": "127.0.0.1",
            "BRIAREUS_NODE_ID": "test",
            "CONTROL_PANEL_URL": "http://127.0.0.1:1",
            "CONTROL_PANEL_UI_URL": "http://127.0.0.1:1",
        }
        cases = (
            {"GATEWAY_PRIVATE_PREVIEW": "true"},
            {"RUST_GATEWAY_SHADOW_ONLY": "true", "BIND_HOST": "0.0.0.0"},
            {"GATEWAY_PRIVATE_PREVIEW": "true", "BIND_HOST": "0.0.0.0"},
            {"RUST_GATEWAY_SHADOW_ONLY": "true", "GATEWAY_PRIVATE_PREVIEW": "true"},
        )
        for variables in cases:
            with self.subTest(variables=variables):
                env = {**os.environ, **base, **variables}
                for key in ("VALKEY_PASSWORD", "OIDC_ISSUER_URL"):
                    env.pop(key, None)
                result = subprocess.run(
                    [str(BINARY)], env=env, capture_output=True, timeout=5, check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Rust Gateway requires", result.stderr)


if __name__ == "__main__":
    unittest.main()
