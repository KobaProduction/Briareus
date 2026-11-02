"""Workspace identity, shared mounts and data preservation; only disposable fixture data."""

import asyncio
import os
import stat
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from journal_fixture import JournalFixture as Journal
from node_agent.application.placement import ApplyPlacement
from node_agent.docker_engine import container_config
from node_agent.infrastructure.container_models import VolumeMount, VolumeOptions
from node_agent.infrastructure.placement import JournalOperationStore
from node_agent.journal import OperationConflict
from node_agent.workspace_init import MARKER, WorkspaceMarker, initialize
from node_agent.workspace_runtime import initializer_config, volume_name
from test_apply_placement_use_case import RuntimeFixture
from test_reconciliation import fixture

from node_protocol import Deployment, WorkspaceMount


class WorkspaceTests(unittest.TestCase):
    def test_workspace_mount_is_shared_by_project_and_confined_to_data_subpath(self) -> None:
        _, first = fixture()
        first = first.model_copy(update={"workspace": WorkspaceMount(id=uuid4())})
        second = first.model_copy(
            update={
                "id": uuid4(),
                "release": first.release.model_copy(update={"module": "terminal"}),
            }
        )
        self.assertEqual(volume_name(first), volume_name(second))
        foreign = first.model_copy(update={"project_uuid": uuid4()})
        self.assertNotEqual(volume_name(first), volume_name(foreign))
        worker = container_config(first)
        self.assertEqual(
            worker.host.mounts,
            [
                VolumeMount(
                    source=volume_name(first),
                    target="/project-data",
                    read_only=False,
                    options=VolumeOptions(no_copy=True, subpath="data"),
                )
            ],
        )
        self.assertIsNone(worker.host.binds)
        self.assertEqual(worker.user, "1000:1000")
        helper = initializer_config(first, "registry.example/node@sha256:" + "a" * 64)
        self.assertEqual(helper.host.network_mode, "none")
        self.assertFalse(helper.host.privileged)
        self.assertEqual(helper.host.cap_add, ["CHOWN"])
        self.assertIsNone(helper.host.binds)
        for wrong in [
            first.model_copy(
                update={"release": first.release.model_copy(update={"run_as": "1001:1001"})}
            ),
            first.model_copy(update={"project_workspace": first.workspace}),
        ]:
            with self.assertRaises(ValueError):
                Deployment.model_validate_json(wrong.model_dump_json())

    def test_storage_change_never_stops_the_existing_worker(self) -> None:
        async def scenario() -> None:
            node, spec = fixture()
            spec = spec.model_copy(update={"workspace": WorkspaceMount(id=uuid4())})
            with tempfile.TemporaryDirectory() as folder:
                journal = Journal(Path(folder) / "journal-fixture")
                journal.seed_applied(spec, "a" * 64)
                runtime = RuntimeFixture()
                try:
                    with self.assertRaises(OperationConflict):
                        await ApplyPlacement(
                            lambda: node, JournalOperationStore(journal), runtime
                        ).execute(
                            uuid4(),
                            1,
                            spec.model_copy(update={"workspace": WorkspaceMount(id=uuid4())}),
                        )
                    self.assertEqual(runtime.actions, [])
                finally:
                    (await journal.close())

        asyncio.run(scenario())


@unittest.skipUnless(
    os.name == "posix" and os.geteuid() == 0,
    "Requires disposable Linux uid-0 fixture with namespace CHOWN",
)
class WorkspaceFilesystemTests(unittest.TestCase):
    def identity(self) -> WorkspaceMarker:
        return WorkspaceMarker(
            kind="briareus.workspace",
            node_uuid=str(uuid4()),
            project_uuid=str(uuid4()),
            workspace_uuid=str(uuid4()),
        )

    def test_initialize_preserves_existing_files_and_rejects_foreign_or_changed_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "volume"
            root.mkdir()
            identity = self.identity()
            initialize(str(root), identity)
            self.assertEqual((root.stat().st_uid, stat.S_IMODE(root.stat().st_mode)), (0, 0o700))
            self.assertEqual(
                ((root / "data").stat().st_uid, stat.S_IMODE((root / "data").stat().st_mode)),
                (1000, 0o700),
            )
            # Prepare fixture content without granting DAC_OVERRIDE to the test
            # container; production workers see only the mounted data subtree.
            os.chown(root / "data", 0, 0)
            (root / "data" / "keep.txt").write_text("fixture content")
            os.chown(root / "data" / "keep.txt", 1000, 1000)
            os.chown(root / "data", 1000, 1000)
            initialize(str(root), identity)
            with self.assertRaises(ValueError):
                initialize(str(root), self.identity())
            os.chown(root / "data", 0, 0)
            self.assertEqual((root / "data" / "keep.txt").read_text(), "fixture content")
            os.chown(root / "data", 1000, 1000)
            (root / MARKER).unlink()
            outside = Path(folder) / "outside"
            outside.write_text("untouched")
            (root / MARKER).symlink_to(outside)
            with self.assertRaises(OSError):
                initialize(str(root), identity)
            self.assertEqual(outside.read_text(), "untouched")
            # Cleanup only this disposable fixture; the runtime has no deletion
            # branch for markers, directories, files or persistent volumes.
            os.chown(root / "data", 0, 0)

    def test_unmarked_nonempty_volume_is_never_adopted_or_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "volume"
            root.mkdir()
            (root / "unmanaged.txt").write_text("preserve")
            with self.assertRaises(OSError):
                initialize(str(root), self.identity())
            self.assertEqual((root / "unmanaged.txt").read_text(), "preserve")
            self.assertFalse((root / MARKER).exists())
