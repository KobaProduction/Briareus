import base64
import json
import time
import unittest
from uuid import uuid4
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_protocol.effect import NodeEffectPermit,sign_permit
from authorization._mcp_call_journal import verified_call


class JournalEvidenceTests(unittest.TestCase):
    def test_expired_effect_is_historical_evidence_and_tampering_is_rejected(self):
        key=Ed25519PrivateKey.generate();now=int(time.time())
        permit=NodeEffectPermit(module="terminal",node_uuid=uuid4(),placement_uuid=uuid4(),project_uuid=uuid4(),workspace_uuid=uuid4(),
            actor_uuid=uuid4(),agent_session_uuid=uuid4(),request_uuid=uuid4(),grant_revision=1,
            fingerprint="a"*64,body_digest="b"*64,bearer_digest="c"*64,arguments_digest="d"*64,
            method="tools/call",tool="job_start",resource_id="fixture:"+"x"*80,issued_at=now-20,expires_at=now-16)
        encoded=sign_permit(permit,key)
        self.assertEqual(verified_call(encoded,key.public_key()).actor_uuid,permit.actor_uuid)
        raw=json.loads(base64.b64decode(encoded));raw["permit"]["actor_uuid"]=str(uuid4())
        with self.assertRaises(InvalidSignature):verified_call(base64.b64encode(json.dumps(raw).encode()).decode(),key.public_key())
        with self.assertRaises(ValueError):verified_call(sign_permit(permit.model_copy(update={"method":"initialize","tool":None}),key),key.public_key())
