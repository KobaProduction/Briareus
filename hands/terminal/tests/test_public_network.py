"""Pure placement preflight fixtures; these do not prove a live firewall."""
import unittest
from types import SimpleNamespace
from uuid import uuid4

from modules.terminal._public_network import decode_facts, validate_kernel
from terminal_hand.network_guard import validate_attestation

FACTS = {"subnet": "172.30.8.0/24", "gateway": "172.30.8.1", "dns": ["127.0.0.11"]}
ROUTES = ("Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
          "eth0 00000000 01081EAC 0003 0 0 0 00000000 0 0 0\n"
          "eth0 00081EAC 00000000 0001 0 0 0 00FFFFFF 0 0 0\n")


class PublicNetworkTests(unittest.TestCase):
    def test_exact_controller_identity(self):
        spec = SimpleNamespace(node_uuid=uuid4(), project_uuid=uuid4(), id=uuid4(), fingerprint="a"*64)
        value = dict(FACTS, profile="public", node_uuid=str(spec.node_uuid), project_uuid=str(spec.project_uuid),
            placement_uuid=str(spec.id), fingerprint=spec.fingerprint, bridge="br-0123456789ab",
            policy_sha256="b"*64, ready=True)
        self.assertEqual(validate_attestation(value, spec), FACTS)
        for key, wrong in (("project_uuid",str(uuid4())), ("fingerprint","c"*64), ("ready",1),
                           ("bridge","docker0"), ("policy_sha256","bad"), ("version",1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_attestation(dict(value, **{key:wrong}), spec)

    def test_kernel_routes_and_dns(self):
        validate_kernel(FACTS, {"lo","eth0"}, ROUTES, "", "nameserver 127.0.0.11\n")
        cases = [({"lo","eth0","eth1"},ROUTES,"","nameserver 127.0.0.11"),
            ({"lo","eth0"},ROUTES.replace("01081EAC","02081EAC"),"","nameserver 127.0.0.11"),
            ({"lo","eth0"},ROUTES,"0 0 0 0 0 0 0 0 0 eth0","nameserver 127.0.0.11"),
            ({"lo","eth0"},ROUTES,"","nameserver 8.8.8.8"),
            ({"lo","eth0"},ROUTES+ROUTES.splitlines()[1]+"\n","","nameserver 127.0.0.11")]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_kernel(FACTS,*args)

    def test_no_json_fact_bypass(self):
        for value in ('{"subnet":"172.30.8.0/24","gateway":"172.30.8.1","dns":["127.0.0.11"],"dns":[]}',
                      '{"subnet":"0.0.0.0/0","gateway":"1.1.1.1","dns":["127.0.0.11"]}'):
            with self.assertRaises(ValueError):
                decode_facts(value)
