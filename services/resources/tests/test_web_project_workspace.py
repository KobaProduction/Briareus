"""Shared project storage is selected by UUID, never borrowed across owners."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from fastapi import HTTPException
from node_protocol import WorkspaceMount
from projects.module_placements import project_workspace_binding

class BrowserWorkspaceOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_owner_purpose_and_private_separation(self):
        node,project,private=uuid4(),uuid4(),uuid4()
        mount=WorkspaceMount(id=uuid4())
        good=dict(node_uuid=node,project_uuid=project,purpose="workspace",retention="persistent")
        tx=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(**good)))
        arguments=dict(module="web",node_uuid=node,project_uuid=project,private_storage_uuid=private)
        self.assertEqual(await project_workspace_binding(tx,mount,**arguments),mount)
        for values in ({"node_uuid":uuid4()},{"project_uuid":uuid4()},{"purpose":"browser"},{"retention":"cache"}):
            tx.get.return_value=SimpleNamespace(**{**good,**values})
            with self.assertRaises(HTTPException):await project_workspace_binding(tx,mount,**arguments)
        tx.get.return_value=None
        with self.assertRaises(HTTPException):await project_workspace_binding(tx,mount,**arguments)
        for change in ({"module":"terminal"},{"private_storage_uuid":mount.id}):
            with self.assertRaises(HTTPException):await project_workspace_binding(tx,mount,**{**arguments,**change})
