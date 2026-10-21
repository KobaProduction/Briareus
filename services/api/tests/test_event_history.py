import unittest
from types import SimpleNamespace
from uuid import uuid4
import json
from control_panel_api._realtime_bus import PanelEvents

class Stream:
 def __init__(self,rows):self.rows=rows
 async def xrevrange(self,key,max='+',count=100):
  rows=self.rows if max=='+' else [row for row in self.rows if int(row[0].split('-')[0])<int(max.lstrip('(').split('-')[0])]
  return list(reversed(rows))[:count]
 async def xrange(self,key,count=1):return self.rows[:count]

class HistoryTests(unittest.IsolatedAsyncioTestCase):
 def setup_stream(self):
  self.project=str(uuid4());self.foreign=str(uuid4());self.proof=SimpleNamespace(role='user',user_uuid=uuid4(),projects=[SimpleNamespace(project_uuid=self.project)])
  rows=[]
  for n in range(1,252):
   project=self.project if n%2 else self.foreign
   event={'event_id':str(n),'topic':'mcp.calls','type':'call.completed','scope':{'kind':'project','id':project},'data':{'project_id':project},'occurredAt':'2026-10-20T00:00:00Z'}
   rows.append((str(n)+'-0',{'event':json.dumps(event)}))
  events=PanelEvents();events.client=Stream(rows);return events
 async def test_cursor_continues_without_duplicates_or_foreign_output(self):
  events=self.setup_stream();first=await events.history(proof=self.proof,topics={'mcp.calls'},project=self.project,limit=100)
  self.assertEqual(len(first['items']),100);self.assertTrue(first['has_more'])
  second=await events.history(proof=self.proof,topics={'mcp.calls'},before=first['next_cursor'],project=self.project,limit=100)
  self.assertEqual(len(second['items']),26);self.assertFalse(second['has_more'])
  self.assertFalse({e['event_id'] for e in first['items']}&{e['event_id'] for e in second['items']})
  self.assertTrue(all(e['data']['project_id']==self.project for e in first['items']+second['items']))
 async def test_foreign_project_and_unavailable_broker_fail_closed(self):
  events=self.setup_stream()
  with self.assertRaises(ValueError):await events.history(proof=self.proof,topics={'mcp.calls'},project=self.foreign)
  events.client=None
  with self.assertRaises(ValueError):await events.history(proof=self.proof,topics={'mcp.calls'})
 async def test_expired_cursor_reports_retention_gap(self):
  events=self.setup_stream();events.client.rows=events.client.rows[50:]
  result=await events.history(proof=self.proof,topics={'mcp.calls'},before='1-0')
  self.assertTrue(result['retention_gap']);self.assertFalse(result['has_more'])

if __name__=='__main__':unittest.main()
