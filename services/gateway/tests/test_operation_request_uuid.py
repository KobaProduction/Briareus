import json
import unittest
from uuid import uuid4
from bridge._node_routing import operation_request_uuid

class OperationRequestUuidTests(unittest.TestCase):
    def test_original_operation_uuid_is_kept_for_all_module_calls(self):
        operation=uuid4()
        for tool in ("analysis_start","web_operation_start","svc_operation_start","infrastructure_operation_start","serena_operation_start"):
            body=json.dumps({"jsonrpc":"2.0","id":str(operation),"method":"tools/call","params":{"name":tool,"arguments":{}}}).encode()
            self.assertEqual(operation_request_uuid(body),operation)

    def test_legacy_nonuuid_ids_and_initialization_keep_fresh_private_request_ids(self):
        for identifier,method in ((1,"tools/call"),("text-id","tools/call"),(str(uuid4()).upper(),"tools/call"),(str(uuid4()),"initialize")):
            body=json.dumps({"jsonrpc":"2.0","id":identifier,"method":method,"params":{}}).encode()
            first,second=operation_request_uuid(body),operation_request_uuid(body)
            self.assertEqual(first.version,4)
            self.assertNotEqual(first,second)
