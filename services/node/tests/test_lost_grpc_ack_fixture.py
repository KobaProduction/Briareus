"""Fault injection must be exact, one-shot, and preserve real upstream authority."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import grpc
from acceptance_lost_grpc_ack import DropAcceptedApply


class LostAckFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_accepted_reply_is_discarded_once_without_retry_or_modification(self):
        node,operation=uuid4(),uuid4()
        request=SimpleNamespace(command=SimpleNamespace(node_uuid=str(node),operation_uuid=str(operation),sequence=11))
        reply=SimpleNamespace(proof=SimpleNamespace(operation_uuid=str(operation),status_code=202))
        upstream=SimpleNamespace(Apply=AsyncMock(return_value=reply))
        context=SimpleNamespace(abort=AsyncMock(side_effect=RuntimeError('dropped')))
        proxy=DropAcceptedApply(upstream,node,operation)
        with self.assertRaisesRegex(RuntimeError,'dropped'):await proxy.Apply(request,context)
        upstream.Apply.assert_awaited_once_with(request,timeout=5)
        context.abort.assert_awaited_once_with(grpc.StatusCode.UNAVAILABLE,'Local acceptance fixture discarded accepted Apply reply')
        self.assertIs(await proxy.Apply(request,context),reply)
        self.assertEqual(upstream.Apply.await_count,2)
        self.assertEqual(context.abort.await_count,1)

    async def test_other_identity_or_rejected_upstream_is_never_marked_as_lost_acceptance(self):
        node,operation=uuid4(),uuid4()
        for foreign,status in ((True,202),(False,403)):
            request=SimpleNamespace(command=SimpleNamespace(node_uuid=str(uuid4() if foreign else node),operation_uuid=str(operation),sequence=11))
            reply=SimpleNamespace(proof=SimpleNamespace(operation_uuid=str(operation),status_code=status))
            proxy=DropAcceptedApply(SimpleNamespace(Apply=AsyncMock(return_value=reply)),node,operation)
            context=SimpleNamespace(abort=AsyncMock())
            self.assertIs(await proxy.Apply(request,context),reply)
            self.assertFalse(proxy.dropped)
            context.abort.assert_not_awaited()
