"""Workspace creation stays independent of any MCP placement or worker."""

import json
import asyncio
import os
import unittest
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select

from node_protocol.management import ModuleCommand
from projects._node_persistence import NodeRow, NodeStorageRow, NodeModuleRow
from test_node_management import NodeManagementFixture


@unittest.skipUnless(
    os.environ.get("NODE_SCHEMA_ACCEPTANCE") == "1", "Explicit disposable Resources DB required"
)
class ProjectWorkspaceTests(NodeManagementFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        command = self.command(action="register", registration=self.registration())
        await self.endpoint(command, self.request)
        self.node = command.registration.id
        async with self.db.transaction() as tx:
            node = await tx.get(NodeRow, self.node)
            node.enabled = True
            node.public_key = "workspace-test-public-pin"

    def workspace_command(self, action, node=None, operation=None):
        command = self.command(
            action="modules", module=ModuleCommand(action=action, node_uuid=node or self.node)
        )
        return command.model_copy(update={"operation_uuid": operation}) if operation else command

    async def test_ensure_reuses_canonical_storage_without_files_or_worker(self):
        command = self.workspace_command("ensure_workspace")
        first = json.loads((await self.endpoint(command, self.request)).body)["item"]
        replay = json.loads((await self.endpoint(command, self.request)).body)["item"]
        another = json.loads(
            (await self.endpoint(self.workspace_command("ensure_workspace"), self.request)).body
        )["item"]
        self.assertEqual(first, replay)
        self.assertEqual(first, another)
        listed = json.loads(
            (await self.endpoint(self.workspace_command("workspaces"), self.request)).body
        )["items"]
        self.assertEqual(listed, [first])
        async with self.db.transaction() as tx:
            storage = await tx.get(NodeStorageRow, UUID(first["id"]))
            self.assertEqual(
                (storage.node_uuid, storage.project_uuid, storage.purpose, storage.retention),
                (self.node, self.project, "workspace", "persistent"),
            )
            self.assertIsNone(
                await tx.scalar(select(NodeModuleRow).where(NodeModuleRow.node_uuid == self.node))
            )

    async def test_scope_and_replay_identity_cannot_borrow_another_node(self):
        async with self.db.transaction() as tx:
            node = await tx.get(NodeRow, self.node)
            node.scope = "personal"
            node.owner_uuid = uuid4()
        with self.assertRaises(HTTPException) as failure:
            await self.endpoint(self.workspace_command("ensure_workspace"), self.request)
        self.assertEqual(failure.exception.status_code, 403)
        async with self.db.transaction() as tx:
            self.assertIsNone(
                await tx.scalar(select(NodeStorageRow).where(NodeStorageRow.node_uuid == self.node))
            )

    async def test_concurrent_requests_reuse_one_project_node_workspace(self):
        results = await asyncio.gather(
            *[
                self.endpoint(self.workspace_command("ensure_workspace"), self.request)
                for _ in range(2)
            ]
        )
        self.assertEqual(json.loads(results[0].body)["item"], json.loads(results[1].body)["item"])
        async with self.db.transaction() as tx:
            rows = list(
                await tx.scalars(
                    select(NodeStorageRow).where(
                        NodeStorageRow.node_uuid == self.node,
                        NodeStorageRow.project_uuid == self.project,
                        NodeStorageRow.purpose == "workspace",
                    )
                )
            )
            self.assertEqual(len(rows), 1)
