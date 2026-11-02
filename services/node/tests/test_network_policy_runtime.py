"""Disposable engine model: policy precedes workers; private proof is immutable."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from node_agent.docker_engine import DockerEngine, EngineFailure
from node_agent.network_policy import NetworkPolicy, PolicyReadback, helper_config, helper_name
from node_agent.network_policy_runtime import (
    _helper,
    _json_log,
    prepare_direct_network,
    recover_network_policy_helpers,
)
from node_agent.workspace_init import initialize_runtime, validate_attestation
from policy_daemon_fixture import IMAGE, PolicyHelperDaemon, PolicyNetworkDaemon, helper_inspection
from test_native_replacement_repair import NativeDaemon
from test_reconciliation import fixture

from node_protocol.network_attestation import PublicNetworkAttestation


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def engine(self, daemon: NativeDaemon) -> DockerEngine:
        engine = await self.enterAsyncContext(daemon.engine())
        engine.utility_image = IMAGE
        engine.control_addresses = ("127.0.0.1", "1.1.1.1")
        return engine

    async def test_empty_bridge_apply_then_readback_and_exact_manifest(self) -> None:
        _, spec = fixture()
        daemon = PolicyNetworkDaemon(spec)
        engine = await self.engine(daemon)
        helper = AsyncMock()
        with patch("node_agent.network_policy_runtime._helper", helper):
            manifest = await prepare_direct_network(engine, spec)
        self.assertEqual([call.args[2] for call in helper.await_args_list], ["apply", "readback"])
        validate_attestation(manifest, spec.node_uuid, spec.project_uuid, spec.container_name)
        self.assertFalse(any(path.endswith("/connect") for _, path in daemon.seen))
        engine.control_addresses = ()
        with patch("node_agent.network_policy_runtime._helper", AsyncMock()) as helper:
            with self.assertRaises(EngineFailure):
                await prepare_direct_network(engine, spec)
            helper.assert_not_awaited()

    async def test_resume_readback_only_and_fail_closed_exact_worker(self) -> None:
        _, spec = fixture()
        daemon = PolicyNetworkDaemon(spec, running=True)
        engine = await self.engine(daemon)
        with patch(
            "node_agent.network_policy_runtime._helper",
            AsyncMock(side_effect=EngineFailure("missing rule")),
        ) as helper, self.assertRaises(EngineFailure):
            await prepare_direct_network(engine, spec)
        assert helper.await_args is not None
        self.assertEqual(helper.await_args.args[2], "readback")
        self.assertEqual(
            [path for method, path in daemon.seen if method == "POST"],
            ["/containers/" + "c" * 64 + "/stop"],
        )
        daemon.network.containers["c" * 64].name = "foreign"
        with patch("node_agent.network_policy_runtime._helper", AsyncMock()) as helper:
            with self.assertRaises(EngineFailure):
                await prepare_direct_network(engine, spec)
            helper.assert_not_awaited()

    async def test_helper_lifecycle_cleanup_and_verified_recovery(self) -> None:
        _, spec = fixture()
        policy = NetworkPolicy(
            str(spec.node_uuid), str(spec.id), "br-" + "b" * 12, "172.30.0.0/24", ("127.0.0.1",)
        )
        daemon = PolicyHelperDaemon(spec)
        engine = await self.engine(daemon)
        result = await _helper(engine, policy, "apply")
        self.assertEqual(result.fingerprint, policy.fingerprint)
        self.assertIsNone(daemon.helper)
        daemon.exit_code = 1
        with self.assertRaises(EngineFailure):
            await _helper(engine, policy, "readback")
        self.assertIsNone(daemon.helper)
        config = helper_config(policy, IMAGE)
        daemon.helper = helper_inspection(config, helper_name(policy))
        await recover_network_policy_helpers(engine, spec.node_uuid)
        self.assertIsNone(daemon.helper)
        daemon.helper = helper_inspection(config, helper_name(policy))
        daemon.helper.host.binds = ["/:/host"]
        before = len(daemon.seen)
        with self.assertRaises(EngineFailure):
            await recover_network_policy_helpers(engine, spec.node_uuid)
        self.assertTrue(all(method == "GET" for method, _ in daemon.seen[before:]))

    def test_bounded_clean_docker_log_frames(self) -> None:
        expected = PolicyReadback(
            fingerprint="a" * 64, bridge="br-" + "b" * 12, netns_inode=123, rootless_owner_uid=2201
        )
        raw = expected.model_dump_json().encode()
        frame = bytes([1, 0, 0, 0]) + len(raw).to_bytes(4, "big") + raw
        self.assertEqual(_json_log(frame), expected)
        incomplete = b'{"state":"ready"}'
        incomplete_frame = bytes([1, 0, 0, 0]) + len(incomplete).to_bytes(4, "big") + incomplete
        for value in (raw, bytes([2]) + frame[1:], frame[:-1], b"x" * 65537, incomplete_frame):
            with self.assertRaises(EngineFailure):
                _json_log(value)

    @unittest.skipUnless(
        hasattr(os, "geteuid") and os.geteuid() == 0, "rootless initializer Linux fixture"
    )
    def test_private_attestation_publish_idempotence_and_no_overwrite(self) -> None:
        _, spec = fixture()
        manifest = PublicNetworkAttestation(
            profile="public",
            node_uuid=spec.node_uuid,
            project_uuid=spec.project_uuid,
            placement_uuid=spec.id,
            fingerprint=spec.fingerprint,
            bridge="br-" + "b" * 12,
            subnet="172.30.0.0/24",
            gateway="172.30.0.1",
            dns=["127.0.0.11"],
            policy_sha256="d" * 64,
            ready=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            os.chmod(temporary, 0o700)
            initialize_runtime(temporary, spec.container_name, manifest)
            target = Path(temporary) / "workers" / spec.container_name / "network-policy.json"
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_nlink, 1)
            initialize_runtime(temporary, spec.container_name, manifest)
            changed = manifest.model_copy(update={"policy_sha256": "e" * 64})
            with self.assertRaises(ValueError):
                initialize_runtime(temporary, spec.container_name, changed)
            self.assertEqual(
                PublicNetworkAttestation.model_validate_json(target.read_bytes()), manifest
            )
            target.unlink()
            target.symlink_to("/etc/passwd")
            with self.assertRaises(OSError):
                initialize_runtime(temporary, spec.container_name, manifest)


if __name__ == "__main__":
    unittest.main()
