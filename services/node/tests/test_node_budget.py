"""Budget changes stay inside bootstrap capacity and preserve running workers."""
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import NodeBudget, ResourceLimits
from node_protocol.control import ControlCommand
from node_agent.control_auth import CoreVerifier
from node_agent.identity import NodeIdentity
from node_agent.journal import Journal
from node_agent.server import create_app
from test_reconciliation import fixture


def budget(cpu=2000, memory=2048):
    return NodeBudget(total=ResourceLimits(memory_bytes=memory*1024**2,cpu_millis=cpu,pids=512),
        reserved=ResourceLimits(memory_bytes=384*1024**2,cpu_millis=750,pids=192))


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_workers_rejects_ceiling_and_shrink_and_restores_journal(self):
        original,spec=fixture()
        ceiling=original.model_copy(update={"budget":budget(4000)})
        current=ceiling.model_copy(update={"budget":budget(1000,1024)})
        key=Ed25519PrivateKey.generate()
        verifier=CoreVerifier(key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo),ceiling.id)
        class Engine:
            # Only observations are available; any runtime mutation fails this fixture.
            async def verify_rootless(self): pass
            async def containers(self,node): return [{"Id":"a"*64}]
            async def inspect(self,container):
                return {"Config":{"Labels":{"io.briareus.deployment":str(spec.id),"io.briareus.spec":spec.fingerprint}},
                    "HostConfig":{"Memory":128*1024**2,"NanoCpus":200_000_000,"PidsLimit":32},
                    "State":{"Running":True,"Health":{"Status":"healthy"}}}
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/"journal.sqlite")
            identity=NodeIdentity(Path(folder)/"key")
            journal.configure(3,current)
            engine=Engine()
            app=create_app(ceiling,engine,journal,verifier,identity)
            async def change(value,sequence):
                command=ControlCommand(node_uuid=ceiling.id,operation_uuid=uuid4(),action="configure",
                    sequence=sequence,node_record=value,issued_at=int(time.time()),expires_at=int(time.time())+20)
                return await app.state.node_control(command)
            try:
                expanded=current.model_copy(update={"budget":budget(2000)})
                self.assertEqual((await change(expanded,4))[0],200)
                self.assertEqual((await change(expanded,4))[0],200)
                self.assertEqual((await change(current.model_copy(update={"budget":budget(5000)}),5))[0],409)
                too_small=current.model_copy(update={"budget":budget(800,512)})
                self.assertEqual((await change(too_small,5))[0],409)
                self.assertEqual(journal.configuration()["sequence"],4)
                # Restart restores the allocation, retaining the larger local ceiling.
                restored=create_app(ceiling,engine,journal,verifier,identity)
                self.assertIsNotNone(restored.state.node_control)
                with self.assertRaises(ValueError):
                    create_app(ceiling.model_copy(update={"budget":budget(1000,1024)}),engine,journal,verifier,identity)
            finally:
                journal.close()
