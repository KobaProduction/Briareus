"""Policy fixtures. Kernel mode runs ONLY inside an explicitly isolated netns.

No live Docker daemon or host firewall is used. The native fixture creates its
own router/bridge/worker/WAN namespaces, then drops the worker's capabilities.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from node_agent.network_policy import (
    PRIVATE_V4,
    NetworkPolicy,
    PolicyAction,
    PolicyCommand,
    PolicyInput,
    PolicyReadback,
    PolicyUnavailable,
)
from pydantic import BaseModel, ConfigDict


class NetworkPolicyTests(unittest.TestCase):
    def policy(
        self,
        *,
        docker_version: str = "28.3.2",
        bridge: str = "br-123456789abc",
        control_addresses: tuple[str, ...] = ("1.1.1.1",),
    ) -> NetworkPolicy:
        return NetworkPolicy(
            str(uuid4()), str(uuid4()), bridge, "172.30.77.0/24", control_addresses, docker_version
        )

    def test_version_and_namespace_interface_inputs_are_fixed(self) -> None:
        with self.assertRaises((ValueError, PolicyUnavailable)):
            self.policy(docker_version="29.5.0")
        for bridge in ("eth0", "br-123;bad"):
            with self.assertRaises((ValueError, PolicyUnavailable)):
                self.policy(bridge=bridge)
        for controls in ((), ("1.1.1.1", "1.1.1.1")):
            with self.assertRaises((ValueError, PolicyUnavailable)):
                self.policy(control_addresses=controls)

    def test_private_metadata_control_ipv4_and_all_ipv6_are_denied(self) -> None:
        policy = self.policy()
        for address in (
            "10.1.2.3",
            "172.30.77.1",
            "192.168.1.1",
            "127.0.0.1",
            "169.254.169.254",
            "100.100.100.200",
        ):
            self.assertTrue(
                any(
                    ipaddress.ip_address(address) in ipaddress.ip_network(value)
                    for value in PRIVATE_V4
                )
            )
        rules = policy.rules(4)
        self.assertIn(("-A", policy.chain(4, "F"), "-d", "1.1.1.1/32", "-j", "DROP"), rules)
        self.assertEqual(
            policy.rules(6),
            [
                ("-A", policy.chain(6, "F"), "-j", "DROP"),
                ("-A", policy.chain(6, "I"), "-j", "DROP"),
            ],
        )
        self.assertNotIn("--flush", policy.restore_script(4))
        self.assertNotIn("-F DOCKER", policy.restore_script(4))

    def test_fingerprint_changes_with_deny_set_but_chain_owner_is_stable(self) -> None:
        policy = self.policy()
        changed = NetworkPolicy(
            policy.node_uuid, policy.placement_uuid, policy.bridge, policy.ipv4_subnet, ("8.8.8.8",)
        )
        self.assertNotEqual(policy.fingerprint, changed.fingerprint)
        self.assertEqual(policy.owner, changed.owner)


def run(*arguments: str, stdin_text: str | None = None) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed namespace fixture argv; no shell or caller input
        arguments, input=stdin_text, text=True, capture_output=True, timeout=10, check=False
    )
    if result.returncode:
        raise AssertionError(
            "Fixture command failed: " + str(arguments[:3]) + " " + result.stderr[:500]
        )
    return result.stdout


NATIVE = os.environ.get("BRIAREUS_ISOLATED_NETNS_FIXTURE") == "1"


class ProbeFacts(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    connected: bool
    capabilities: int


@unittest.skipUnless(NATIVE, "Run only in a fresh rootless user+network namespace")
class IsolatedKernelTests(unittest.TestCase):
    holders: ClassVar[list[subprocess.Popen[str]]] = []
    policy: ClassVar[NetworkPolicy]
    wan: ClassVar[subprocess.Popen[str]]
    worker: ClassVar[subprocess.Popen[str]]
    other: ClassVar[subprocess.Popen[str]]
    control_stop: ClassVar[threading.Event | None] = None
    control_server: ClassVar[socket.socket | None] = None
    control_thread: ClassVar[threading.Thread | None] = None

    @classmethod
    def setUpClass(cls) -> None:
        mappings = [
            tuple(map(int, line.split()))
            for line in Path("/proc/self/uid_map").read_text().splitlines()
        ]
        expected_host = int(os.environ["BRIAREUS_FIXTURE_HOST_NETNS"])
        if (
            not mappings
            or mappings[0][1] == 0
            or os.stat("/proc/self/ns/net").st_ino == expected_host
        ):
            raise AssertionError("Fixture refuses the real host/daemon network namespace")
        cls.holders = []
        cls.policy = NetworkPolicy(
            str(uuid4()), str(uuid4()), "br-123456789abc", "172.30.77.0/24", ("1.1.1.1",)
        )
        try:
            cls.wan = cls.namespace()
            cls.worker = cls.namespace()
            cls.other = cls.namespace()
            run("ip", "link", "set", "lo", "up")
            run("sysctl", "-w", "net.ipv4.ip_forward=1")
            run("iptables", "-N", "DOCKER-USER")
            run("iptables", "-I", "FORWARD", "1", "-j", "DOCKER-USER")
            cls.bridge(
                "br-123456789abc",
                "172.30.77.1/24",
                "vworker",
                "worker0",
                cls.worker.pid,
                "172.30.77.2/24",
            )
            cls.bridge(
                "br-abcdef123456",
                "172.31.88.1/24",
                "vother",
                "other0",
                cls.other.pid,
                "172.31.88.2/24",
            )
            run("ip", "link", "add", "wanroot", "type", "veth", "peer", "name", "wan0")
            run("ip", "link", "set", "wan0", "netns", str(cls.wan.pid))
            run("ip", "addr", "add", "198.18.42.1/30", "dev", "wanroot")
            run("ip", "link", "set", "wanroot", "up")
            cls.in_ns(cls.wan.pid, "ip", "addr", "add", "198.18.42.2/30", "dev", "wan0")
            cls.in_ns(cls.wan.pid, "ip", "link", "set", "wan0", "up")
            cls.in_ns(cls.wan.pid, "ip", "route", "add", "default", "via", "198.18.42.1")
            for address in ("93.184.216.34", "10.77.0.2", "1.1.1.1", "169.254.169.254"):
                cls.in_ns(cls.wan.pid, "ip", "addr", "add", address + "/32", "dev", "wan0")
                run("ip", "route", "add", address + "/32", "via", "198.18.42.2", "dev", "wanroot")
            assert cls.wan.stdin is not None and cls.wan.stdout is not None
            cls.wan.stdin.write("serve\n")
            cls.wan.stdin.flush()
            if cls.wan.stdout.readline().strip() != "ready":
                raise AssertionError("Fixture WAN did not start")
            server = cls.control_server = socket.socket()
            server.settimeout(0.2)
            server.bind(("0.0.0.0", 8181))  # noqa: S104 -- isolated fixture namespace only
            server.listen(16)
            stop = cls.control_stop = threading.Event()

            def serve_control() -> None:
                while not stop.is_set():
                    try:
                        connection, _ = server.accept()
                    except (OSError, TimeoutError):
                        continue
                    with connection:
                        connection.sendall(b"fixture")

            cls.control_thread = threading.Thread(target=serve_control, daemon=True)
            cls.control_thread.start()
            if not cls.probe(cls.worker.pid, "172.30.77.1") or not cls.probe(
                cls.worker.pid, "10.77.0.2"
            ):
                raise AssertionError(
                    "Private fixture control destinations were not reachable before policy"
                )
            cls.helper("apply")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def namespace(cls) -> subprocess.Popen[str]:
        process = subprocess.Popen(  # noqa: S603 -- fixed private namespace holder argv
            ["/usr/bin/unshare", "--net", "--", sys.executable, __file__, "--hold"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        cls.holders.append(process)
        assert process.stdout is not None
        if process.stdout.readline().strip() != "held":
            raise AssertionError("Private fixture namespace unavailable")
        cls.in_ns(process.pid, "ip", "link", "set", "lo", "up")
        return process

    @staticmethod
    def in_ns(pid: int, *arguments: str) -> str:
        return run("nsenter", "--target", str(pid), "--net", "--", *arguments)

    @classmethod
    def bridge(
        cls, name: str, address: str, host_link: str, peer_link: str, pid: int, peer_address: str
    ) -> None:
        run("ip", "link", "add", name, "type", "bridge")
        run("ip", "addr", "add", address, "dev", name)
        run("ip", "link", "set", name, "up")
        run("ip", "link", "add", host_link, "type", "veth", "peer", "name", peer_link)
        run("ip", "link", "set", host_link, "master", name)
        run("ip", "link", "set", host_link, "up")
        run("ip", "link", "set", peer_link, "netns", str(pid))
        cls.in_ns(pid, "ip", "addr", "add", peer_address, "dev", peer_link)
        cls.in_ns(pid, "ip", "link", "set", peer_link, "up")
        cls.in_ns(pid, "ip", "route", "add", "default", "via", address.split("/")[0])

    @classmethod
    def helper(cls, operation: PolicyAction) -> PolicyReadback:
        request = PolicyCommand(
            action=operation, policy=PolicyInput.from_domain(cls.policy)
        ).model_dump_json()
        result = run(
            "setpriv",
            "--no-new-privs",
            "--bounding-set=-all,+net_admin",
            sys.executable,
            "-m",
            "node_agent.network_policy",
            stdin_text=request,
        )
        data = PolicyReadback.model_validate_json(result)
        if data.fingerprint != cls.policy.fingerprint or data.state != "ready":
            raise AssertionError("Kernel policy readback differs")
        return data

    @classmethod
    def probe(cls, pid: int, address: str, protocol: str = "tcp") -> bool:
        result = cls.in_ns(
            pid,
            "setpriv",
            "--no-new-privs",
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            sys.executable,
            __file__,
            "--probe",
            address,
            protocol,
        )
        data = ProbeFacts.model_validate_json(result)
        if data.capabilities != 0:
            raise AssertionError("Fixture worker retained capabilities")
        return data.connected

    def test_direct_public_tcp_and_udp_dns_with_capability_free_worker(self) -> None:
        self.assertTrue(self.probe(self.worker.pid, "93.184.216.34"))
        self.assertTrue(self.probe(self.worker.pid, "93.184.216.34", "udp"))

    def test_private_core_and_metadata_are_denied_without_affecting_other_worker(self) -> None:
        for address in ("172.30.77.1", "10.77.0.2", "1.1.1.1", "169.254.169.254"):
            self.assertFalse(self.probe(self.worker.pid, address))
            self.assertTrue(self.probe(self.other.pid, address))

    def test_apply_is_idempotent_and_readback_matches(self) -> None:
        self.helper("apply")
        self.helper("readback")
        self.assertTrue(self.probe(self.worker.pid, "93.184.216.34"))

    @classmethod
    def tearDownClass(cls) -> None:
        if (
            cls.control_stop is not None
            and cls.control_server is not None
            and cls.control_thread is not None
        ):
            cls.control_stop.set()
            cls.control_server.close()
            cls.control_thread.join(timeout=2)
        for process in cls.holders:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def hold() -> None:
    print("held", flush=True)
    if sys.stdin.readline().strip() != "serve":
        time.sleep(60)
        return

    async def serve() -> None:
        async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            del reader
            writer.write(b"fixture")
            await writer.drain()
            writer.close()

        class UDP(asyncio.DatagramProtocol):
            transport: asyncio.DatagramTransport

            def connection_made(self, transport: asyncio.BaseTransport) -> None:
                if not isinstance(transport, asyncio.DatagramTransport):
                    raise TypeError("Datagram fixture transport required")
                self.transport = transport

            def datagram_received(self, data: bytes, address: tuple[str, int]) -> None:
                self.transport.sendto(data, address)

        server = await asyncio.start_server(answer, "0.0.0.0", 8181)  # noqa: S104 -- isolated fixture WAN
        await asyncio.get_running_loop().create_datagram_endpoint(
            UDP, local_addr=("93.184.216.34", 53)
        )
        print("ready", flush=True)
        async with server:
            await server.serve_forever()

    asyncio.run(serve())


def probe() -> None:
    address, protocol = sys.argv[2:]
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    kind = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    connected = False
    with socket.socket(socket.AF_INET, kind) as connection:
        connection.settimeout(0.5)
        try:
            connection.connect((address, 8181 if protocol == "tcp" else 53))
            if protocol == "udp":
                connection.send(b"fixture")
            connected = connection.recv(64) == b"fixture"
        except OSError:
            pass
    print(
        ProbeFacts(
            connected=connected, capabilities=int(fields["CapEff"].strip(), 16)
        ).model_dump_json()
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--hold"]:
        hold()
    elif sys.argv[1:2] == ["--probe"]:
        probe()
    else:
        unittest.main()
