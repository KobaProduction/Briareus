"""Bounded private operation handles; ProcessLease remains execution authority.

The adapter owns the lock and must dispatch control before changing identity,
and reject unrelated native calls while running. No effect is ever retried.
"""
import asyncio
import json
import time
from uuid import uuid4


class DeferredCalls:
    def __init__(self,module,*,lock,lease,ready,tools,execute,stop,recover):
        self.prefix=module+'_operation_'
        self.lock,self.lease,self.ready,self.tools=lock,lease,ready,tools
        self.execute,self.stop,self.recover=execute,stop,recover
        self.boot=str(uuid4());self.records={}

    def lookup(self, operation_id):
        if not isinstance(operation_id,str):return None
        return self.records.get(self.boot+":"+operation_id[8:] if operation_id.startswith("request:") else operation_id)

    def running(self):
        return any(record['state']=='running' for record in self.records.values())

    def interrupt(self):
        for record in self.records.values():
            if record['state']=='running':
                record['state']='interrupted'
                task=record.get('task')
                if task is not None and task is not asyncio.current_task():task.cancel()

    @staticmethod
    def result(record):
        value={key:record[key] for key in ('operation_id','tool','state')}
        if 'result' in record:value['result']=record['result']
        return {'content':[{'type':'text','text':'Operation: '+record['state']}],
                'structuredContent':value,'isError':False}

    async def control(self,name,arguments,permit,identity):
        polling=name==self.prefix+'poll'
        if name not in {self.prefix+'poll',self.prefix+'cancel'}:
            raise ValueError('Known operation control required')
        expected={'operation_id','tool'} if polling else {'operation_id'}
        if set(arguments)!=expected or not isinstance(arguments['operation_id'],str):
            raise ValueError('Exact owned operation required')
        record=self.lookup(arguments['operation_id'])
        if (record is None or record['identity']!=identity or permit.expires_at<=time.time()
            or polling and arguments['tool']!=record['tool']):
            raise ValueError('Operation unavailable for this identity and tool')
        if record['state']=='running':
            if not polling:
                await self.stop()
                record['state']='cancelled'
                self.recover()
            else:
                if not self.ready() or self.lease.identity!=identity:
                    raise ValueError('Original prepared execution runtime required')
                await self.lease.grant(identity,permit.expires_at)
        return self.result(record)

    async def start(self,arguments,permit,identity):
        if (set(arguments)!={'tool','arguments'} or not isinstance(arguments['tool'],str)
            or not isinstance(arguments['arguments'],dict) or arguments['tool'] not in self.tools()
            or arguments['tool'].startswith(self.prefix)
            or len(json.dumps(arguments,allow_nan=False).encode())>32000
            or not self.ready() or permit.expires_at<=time.time() or self.running()):
            raise ValueError('Bounded original tool and prepared runtime required')
        operation=self.boot+':'+str(permit.request_uuid)
        if operation in self.records:raise ValueError('Start already received; poll its handle')
        while len(self.records)>=32:self.records.pop(next(iter(self.records)))
        await self.lease.grant(identity,permit.expires_at)
        record={'operation_id':operation,'identity':identity,'tool':arguments['tool'],'state':'running'}
        self.records[operation]=record
        record['task']=asyncio.create_task(self.run(record,arguments['arguments'],permit))
        return self.result(record)

    async def run(self,record,arguments,permit):
        try:
            from .runtime_policy import runtime_policy
            async with asyncio.timeout(runtime_policy().execution_timeout_seconds):
                result=await self.execute(record['tool'],arguments,permit)
            async with self.lock:
                if record['state']=='running':
                    record['result']=result
                    record['state']='failed' if result.get('isError') else 'completed'
        except asyncio.CancelledError:raise
        except Exception:
            async with self.lock:
                await self.stop()
                record['state']='failed'
                self.recover()


def register_deferred_tools(mcp,module):
    prefix=module+'_operation_'
    @mcp.tool(name=prefix+'start')
    async def start(tool:str,arguments:dict[str,object]):
        """Start one long original tool with current authority and retain its handle.

        Use initial_instructions to prepare this identity first. Poll every two
        seconds with the returned operation_id and exact original tool. Native
        processes pause within five seconds without fresh rights. Start/poll
        also require current rights to the original tool. Never blindly retry
        a start whose reply was lost. Only one operation runs per placement.
        Worker replacement invalidates handles and never replays old effects.
        """
        raise RuntimeError('Metadata only; trusted parent executes')

    @mcp.tool(name=prefix+'poll')
    async def poll(operation_id:str,tool:str):
        """Resume an owned operation with current original-tool + start + poll rights.

        If the start reply was lost, operation_id="request:<original start request UUID>" resolves the same operation without replay.

        This may continue an effect, not merely read a result. Another actor,
        AgentSession, revision or tool cannot resume or retrieve the operation.
        """
        raise RuntimeError('Metadata only; trusted parent executes')

    @mcp.tool(name=prefix+'cancel')
    async def cancel(operation_id:str):
        """Stop an owned operation without resuming it or undoing prior effects.

        Native processes stop; project files remain. Cancellation is not rollback.
        """
        raise RuntimeError('Metadata only; trusted parent executes')
