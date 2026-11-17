"""Source ownership: Rust catalog and Watch Paths versus canonical Python V1."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "shared/services/catalog/src"))
from briareus_service_catalog import BUILTIN_SERVICES  # noqa: E402


class GatewayCatalogContract(unittest.TestCase):
    def test_known_rust_services_match_python_identity(self) -> None:
        actual = json.loads((ROOT / "services/gateway-rust/catalog.json").read_text())
        expected = [service.model_dump() for service in BUILTIN_SERVICES]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len({service["id"] for service in actual}))

    def test_preview_is_excluded_from_live_python_gateway_watches(self) -> None:
        catalog = json.loads((ROOT / "deploy/services.json").read_text())
        gateway = next(service for service in catalog["services"] if service["name"] == "gateway")
        self.assertEqual(gateway["directory"], "services/gateway")
        self.assertTrue(
            any(pattern.startswith("services/gateway/") for pattern in gateway["watch_paths"])
        )
        self.assertFalse(
            any(
                "gateway-rust" in pattern
                or "shared/oidc-verifier" in pattern
                or "shared/service-discovery" in pattern
                for pattern in gateway["watch_paths"]
            )
        )
        self.assertFalse(any(service["name"] == "gateway-rust" for service in catalog["services"]))


if __name__ == "__main__":
    unittest.main()
