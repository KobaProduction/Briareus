"""Public routing is immutable and rechecked on every effect, without Linux I/O."""

import json
import unittest
from dataclasses import FrozenInstanceError, dataclass, replace
from unittest.mock import patch

from modules.terminal._public_network import decode_facts, encode_facts, validate_kernel
from pydantic import BaseModel, JsonValue
from terminal_hand.application.public_network import VerifyPublicNetwork
from terminal_hand.domain.public_network import (
    KernelNetwork,
    PublicRouting,
    require_public_supervisor,
)
from terminal_hand.infrastructure.network_inventory import kernel_network

from node_protocol.json_boundary import decode_json, require_json_object

ROUTES = (
    "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
    "eth0 00000000 01081EAC 0003 0 0 0 00000000 0 0 0\n"
    "eth0 00081EAC 00000000 0001 0 0 0 00FFFFFF 0 0 0\n"
)


@dataclass
class InventoryFixture:
    snapshot: KernelNetwork
    calls: int = 0

    def current(self) -> KernelNetwork:
        self.calls += 1
        return self.snapshot


class CodecFixture(BaseModel):
    facts: list[JsonValue]

class NetworkUseCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routing = PublicRouting("172.30.8.0/24", "172.30.8.1", ("127.0.0.11",))
        self.inventory = InventoryFixture(
            kernel_network(frozenset({"lo", "eth0"}), ROUTES, "", "nameserver 127.0.0.11\n")
        )
        self.verify = VerifyPublicNetwork(self.inventory)

    def test_current_inventory_is_not_cached_after_an_earlier_success(self) -> None:
        self.verify.execute(self.routing)
        self.inventory.snapshot = replace(self.inventory.snapshot, interfaces=frozenset({"lo"}))
        with self.assertRaises(ValueError):
            self.verify.execute(self.routing)
        self.assertEqual(self.inventory.calls, 2)

    def test_public_profile_never_selectable_from_a_non_supervisor_identity(self) -> None:
        require_public_supervisor("terminal", "public", 0)
        for module, profile, uid in (
            ("files", "public", 0),
            ("terminal", "public", 1000),
            ("terminal", "private", 0),
        ):
            with (
                self.subTest(module=module, profile=profile, uid=uid),
                self.assertRaises(ValueError),
            ):
                require_public_supervisor(module, profile, uid)

    def test_raw_codec_preserves_json_shape_for_existing_wire_consumers(self) -> None:
        self.assertEqual(
            decode_json(b'{"facts":[1,true,null]}', CodecFixture).facts, [1, True, None]
        )
        self.assertEqual(
            decode_json(bytearray(b'{"facts":["text"]}'), CodecFixture).facts, ["text"]
        )
        with self.assertRaises(ValueError):
            require_json_object(b'"text"')

    def test_raw_codec_rejects_duplicate_nested_keys_and_nonfinite_values(self) -> None:
        for raw in (
            b'{"a":1,"a":2}',
            b'{"nested":{"a":1,"a":2}}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b'{"x":-Infinity}',
            b"\xff",
        ):
            with (
                self.subTest(raw=raw[:60]),
                self.assertRaisesRegex(ValueError, "Invalid bounded JSON"),
            ):
                decode_json(raw, CodecFixture)

    def test_raw_codec_retains_recursion_failure_mapping(self) -> None:
        with (
            patch("node_protocol.json_boundary.json.loads", side_effect=RecursionError),
            self.assertRaisesRegex(ValueError, "Invalid bounded JSON"),
        ):
            require_json_object("[]")

    def test_route_facts_survive_child_environment_round_trip_without_mutability(self) -> None:
        self.assertEqual(decode_facts(encode_facts(self.routing)), self.routing)
        original = {
            "subnet": self.routing.subnet,
            "gateway": self.routing.gateway,
            "dns": ["127.0.0.11"],
        }
        value = decode_facts(json.dumps(original))
        original["dns"] = []
        self.assertEqual(value, self.routing)
        with self.assertRaises(FrozenInstanceError):
            value.__setattr__("subnet", "0.0.0.0/0")

    def test_non_private_or_unusable_routing_facts_are_rejected(self) -> None:
        for subnet, gateway in (
            ("8.8.8.0/24", "8.8.8.1"),
            ("172.30.8.0/24", "172.30.9.1"),
            ("172.30.8.0/24", "172.30.8.0"),
            ("172.30.8.0/24", "172.30.8.255"),
            ("172.30.8.0/31", "172.30.8.1"),
        ):
            with self.subTest(subnet=subnet, gateway=gateway), self.assertRaises(ValueError):
                PublicRouting(subnet, gateway, ("127.0.0.11",))

    def test_missing_duplicate_or_malformed_routes_fail_closed(self) -> None:
        for routes in (
            "",
            ROUTES.splitlines()[0],
            ROUTES + ROUTES.splitlines()[1],
            ROUTES + "eth0 invalid",
            ROUTES.replace("0003", "0001"),
        ):
            with self.subTest(routes=routes), self.assertRaises(ValueError):
                validate_kernel(self.routing, {"lo", "eth0"}, routes, "", "nameserver 127.0.0.11")

    def test_loopback_ipv6_does_not_allow_an_external_ipv6_route(self) -> None:
        validate_kernel(
            self.routing, {"lo", "eth0"}, ROUTES, "0 0 0 0 0 0 0 0 0 lo", "nameserver 127.0.0.11"
        )
        with self.assertRaises(ValueError):
            validate_kernel(
                self.routing,
                {"lo", "eth0"},
                ROUTES,
                "0 0 0 0 0 0 0 0 0 eth0",
                "nameserver 127.0.0.11",
            )
