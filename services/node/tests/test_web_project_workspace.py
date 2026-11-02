"""Optional secondary browser storage preserves old signed deployment wire."""

import hashlib
import json
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_agent.docker_engine import container_config
from node_agent.workspace_runtime import initializer_config, volume_name
from pydantic import ValidationError

from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.grpc_codec import MODULE, decode_deployment, encode_deployment
from node_protocol.management import PlacementUpdate


def fixture(secondary: bool = True) -> Deployment:
    key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return Deployment(
        id=uuid4(),
        node_uuid=uuid4(),
        project_uuid=uuid4(),
        release=ModuleRelease(
            module="web", image="registry.test/web@sha256:" + "a" * 64, lifecycle="sessionful"
        ),
        workspace=WorkspaceMount(id=uuid4()),
        project_workspace=WorkspaceMount(id=uuid4()) if secondary else None,
        effect_verify_key=key,
        limits=ResourceLimits(memory_bytes=1088 * 1024**2, cpu_millis=600, pids=288),
    )


class SharedBrowserWorkspaceTests(unittest.TestCase):
    def test_old_wire_and_optional_proto_roundtrip(self) -> None:
        old = fixture(False)
        self.assertNotIn("project_workspace", old.model_dump(mode="json"))
        legacy = json.dumps(
            old.model_dump(mode="json", exclude={"enabled"}), sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(old.fingerprint, hashlib.sha256(legacy.encode()).hexdigest())
        self.assertFalse(encode_deployment(old).HasField("project_workspace"))
        self.assertEqual(decode_deployment(encode_deployment(old)), old)
        new = fixture()
        self.assertEqual(decode_deployment(encode_deployment(new)), new)
        self.assertEqual(MODULE["serena"], 8)
        self.assertNotIn("radare2", MODULE)

    def test_distinct_web_only_binding_and_private_mount(self) -> None:
        spec = fixture()
        config = container_config(spec)
        mounts = config.host.mounts
        assert mounts is not None
        self.assertEqual(
            [(m.target, m.source) for m in mounts],
            [
                ("/browser", volume_name(spec)),
                ("/workspace/project", volume_name(spec, spec.project_workspace)),
            ],
        )
        secondary = initializer_config(
            spec, "registry.test/node@sha256:" + "b" * 64, workspace=spec.project_workspace
        )
        assert secondary.host.mounts is not None
        self.assertEqual(secondary.host.mounts[0].source, volume_name(spec, spec.project_workspace))
        self.assertIn("BRIAREUS_RUNTIME_WORKER=" + spec.container_name, secondary.environment or [])
        for change in (
            {"project_workspace": spec.workspace},
            {"release": {**spec.release.model_dump(), "module": "files"}},
        ):
            with self.assertRaises(ValidationError):
                Deployment.model_validate({**spec.model_dump(mode="json"), **change})

    def test_update_omission_and_explicit_removal_survive_wire(self) -> None:
        identity, release_uuid = uuid4(), uuid4()
        absent = PlacementUpdate(id=identity, release_uuid=release_uuid, expected_sequence=1)
        self.assertNotIn("project_workspace", absent.model_dump())
        explicit = PlacementUpdate(
            id=identity, release_uuid=release_uuid, expected_sequence=1, project_workspace=None
        )
        self.assertIn("project_workspace", explicit.model_dump())
        self.assertIn(
            "project_workspace",
            PlacementUpdate.model_validate(explicit.model_dump()).model_fields_set,
        )
