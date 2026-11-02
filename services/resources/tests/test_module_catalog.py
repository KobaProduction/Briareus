"""Disposable owner DB: current operator, exact immutable build and receipt replay."""

import json
import os
import unittest
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from projects._node_persistence import ModuleReleaseRow
from test_node_management import NodeManagementFixture

from node_protocol.catalog import ARTIFACTS
from node_protocol.management import ModuleCommand, Publication


@unittest.skipUnless(
    os.environ.get("NODE_SCHEMA_ACCEPTANCE") == "1",
    "Explicit disposable Resources database required",
)
class ModuleCatalogTests(NodeManagementFixture):
    def publication(self, **changes):
        values = dict(
            id=uuid4(),
            module="files",
            source_commit=uuid4().hex + "a" * 8,
            input_fingerprint=uuid4().hex + uuid4().hex,
            image="registry.example/files@sha256:" + "a" * 64,
        )
        values.update(changes)
        return Publication(**values)

    async def test_catalog_publication_replay_and_build_identity_collision(self):
        catalog = json.loads(
            (
                await self.endpoint(
                    self.command(action="modules", module=ModuleCommand(action="catalog")),
                    self.request,
                )
            ).body
        )
        self.assertEqual(
            {row["key"] for row in catalog["artifacts"]},
            {"files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"},
        )
        self.assertTrue(
            next(row for row in catalog["artifacts"] if row["key"] == "files")["node_adapter"]
        )
        value = self.publication()
        command = self.command(
            action="modules", module=ModuleCommand(action="publish", publication=value)
        )
        with patch.dict(os.environ, {"RESOURCES_RELEASE_REGISTRIES": '["registry.example"]'}):
            first = json.loads((await self.endpoint(command, self.request)).body)
            again = json.loads((await self.endpoint(command, self.request)).body)
            self.assertEqual(first, again)
            self.assertEqual(first["release"]["image"], value.image)
            conflict = command.model_copy(update={"operation_uuid": uuid4()})
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(conflict, self.request)
            self.assertEqual(denied.exception.status_code, 409)
            changed = value.model_copy(
                update={"id": uuid4(), "image": "registry.example/files@sha256:" + "b" * 64}
            )
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(
                    self.command(
                        action="modules",
                        module=ModuleCommand(action="publish", publication=changed),
                    ),
                    self.request,
                )
            self.assertEqual(denied.exception.status_code, 409)
        async with self.db.transaction() as tx:
            row = await tx.get(ModuleReleaseRow, value.id)
            self.assertEqual(row.image_reference, value.image)

    async def test_nonoperator_unapproved_registry_and_unready_adapter_cannot_publish(self):
        value = self.publication()
        command = self.command(
            action="modules", module=ModuleCommand(action="publish", publication=value)
        )
        self.role = "user"
        with self.assertRaises(HTTPException) as denied:
            await self.endpoint(command, self.request)
        self.assertEqual(denied.exception.status_code, 403)
        self.role = "operator"
        with patch.dict(os.environ, {"RESOURCES_RELEASE_REGISTRIES": "[]"}):
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(command, self.request)
            self.assertEqual(denied.exception.status_code, 422)
        unready = value.model_copy(update={"module": "terminal"})
        with (
            patch.dict(ARTIFACTS, {"terminal": replace(ARTIFACTS["terminal"], node_adapter=False)}),
            self.assertRaises(HTTPException) as denied,
        ):
            await self.endpoint(
                self.command(
                    action="modules", module=ModuleCommand(action="publish", publication=unready)
                ),
                self.request,
            )
        self.assertEqual(denied.exception.status_code, 409)
        async with self.db.transaction() as tx:
            self.assertIsNone(await tx.get(ModuleReleaseRow, value.id))
