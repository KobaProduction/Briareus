"""Safe authoritative failure facts, durable rollback and wire compatibility."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from node_protocol.diagnostics import diagnostic_wire
from node_protocol.grpc_codec import encode_operation, decode_operation
from node_agent.diagnostics import state_diagnostic
from node_agent.docker_engine import EngineFailure
from node_agent.journal import Journal
from node_agent.server import receipt
from test_reconciliation import fixture, FakeEngine, ObservedController


class OperationDiagnosticTests(unittest.TestCase):
    def test_state_facts_never_copy_logs_or_infer_stack_cause(self):
        actual = state_diagnostic("checking", {"Running":False,"ExitCode":3,"OOMKilled":False,
            "Error":"secret-provider-url","Health":{"Status":"unhealthy","Log":[{"ExitCode":1,"Output":"secret-token"}]}})
        self.assertEqual(actual, {"stage":"checking","component":"worker","reason":"process_exited",
            "exit_code":3,"oom_killed":False,"health_status":"unhealthy","health_exit_code":1})
        self.assertNotIn("secret",json.dumps(actual))
        self.assertEqual(state_diagnostic("checking",{"Running":False,"ExitCode":137,"OOMKilled":True})["reason"],"oom")
        probe=state_diagnostic("checking",{"Running":True,"ExitCode":0,"Health":{"Status":"unhealthy","Log":[{"ExitCode":-1}]}})
        self.assertNotIn("exit_code",probe)
        self.assertEqual(probe["health_exit_code"],-1)
        self.assertEqual(probe["reason"],"unhealthy")
        with self.assertRaises(ValueError):
            diagnostic_wire(dict(actual,message="secret"))
        self.assertIsNone(EngineFailure("Workspace helper cleanup is unresolved secret-token").reason)
        self.assertEqual(EngineFailure("Workspace helper cleanup is unresolved").reason,"workspace_cleanup_uncertain")

    def test_additive_journal_upgrade_preserves_old_data_and_first_failure(self):
        _,spec=fixture()
        operation=uuid4()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"journal.sqlite"
            db=sqlite3.connect(path)
            db.execute("CREATE TABLE operations(id TEXT PRIMARY KEY,placement TEXT NOT NULL,sequence INTEGER NOT NULL,"
                "desired TEXT NOT NULL,fingerprint TEXT NOT NULL,phase TEXT NOT NULL,previous TEXT,container TEXT,error TEXT,UNIQUE(placement,sequence))")
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?,'queued',NULL,NULL,NULL)",
                (str(operation),str(spec.id),1,spec.model_dump_json(),spec.fingerprint))
            db.commit(); db.close()
            journal=Journal(path)
            try:
                self.assertEqual(journal.get(operation)["desired"],spec.model_dump_json())
                self.assertNotIn("diagnostic",receipt(journal.get(operation)))
                original={"stage":"checking","component":"worker","reason":"process_exited","exit_code":3}
                journal.phase(operation,"checking",diagnostic=original)
                journal.phase(operation,"rolling_back",error="UPDATE_FAILED")
                journal.phase(operation,"failed",error="ROLLBACK_FAILED",diagnostic={
                    "stage":"rolling_back","component":"controller","reason":"unknown"})
                self.assertEqual(journal.get(operation)["diagnostic"],original)
                self.assertEqual(receipt(journal.get(operation))["diagnostic"],original)
                self.assertEqual(json.loads(journal.events_after(0)[-1]["payload"])["diagnostic"],original)
            finally:
                journal.close()
            reopened=Journal(path)
            try:
                self.assertEqual(reopened.get(operation)["diagnostic"],original)
                # New operations use explicit columns after the additive ALTER.
                self.assertEqual(reopened.reserve(uuid4(),2,spec)["phase"],"queued")
            finally:
                reopened.close()

    def test_protobuf_roundtrip_and_old_payload_omission(self):
        old={"operation_uuid":str(uuid4()),"sequence":1,"phase":"failed","error":"UPDATE_FAILED"}
        self.assertEqual(decode_operation(encode_operation(old)),old)
        current=dict(old,diagnostic={"stage":"checking","component":"worker","reason":"oom",
            "exit_code":137,"oom_killed":True,"health_status":"unhealthy","health_exit_code":-1})
        self.assertEqual(decode_operation(encode_operation(current)),current)


class ControllerDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_internal_failure_is_durable_before_rollback(self):
        node,spec=fixture()
        class Engine(FakeEngine):
            async def verify_rootless(self):
                raise EngineFailure("Workspace helper recovery requires controller restart")
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/"journal.sqlite")
            try:
                operation=uuid4()
                result=await ObservedController(node,Engine(),journal).apply(operation,1,spec)
                self.assertEqual(result["error"],"UPDATE_FAILED")
                self.assertEqual(result["diagnostic"],{"stage":"queued","component":"engine","reason":"workspace_cleanup_uncertain"})
            finally:
                journal.close()
