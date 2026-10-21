"""Native isolated-parent LSP workflow with short renewed execution leases.

Fixture identities are native test data, NOT Rauthy/Cedar acceptance. No host
project, credentials or network are mounted. Run with the production three-cap
root supervisor profile and UID1000-owned disposable tmpfs data/home.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace
from uuid import uuid4

from serena_hand.supervisor import SerenaSupervisor


async def helper(code,*arguments):
    process=await asyncio.create_subprocess_exec('/opt/serena/.venv/bin/python','-c',code,*arguments,
        user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','PYTHONPATH':'/app/src:/tests'},
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    stdout,stderr=await asyncio.wait_for(process.communicate(),10)
    if process.returncode:raise RuntimeError('Owned fixture helper failed: '+stderr.decode()[-500:])
    return stdout.decode()


async def main(language):
    relative='.deferred-'+language+'-'+uuid4().hex
    setup="from pathlib import Path; import sys; from acceptance_lsp_languages import fixture; p=Path('/project-data')/sys.argv[1];p.mkdir(mode=0o700);fixture(p,sys.argv[2])"
    await helper(setup,relative,language)
    supervisor=SerenaSupervisor(relative)
    actor,session=uuid4(),uuid4()
    stage='startup';paused=False
    def permit():return SimpleNamespace(actor_uuid=actor,agent_session_uuid=session,grant_revision=1,
        request_uuid=uuid4(),expires_at=time.time()+4)
    def text(result):return '\n'.join(item.get('text','') for item in result.get('content',[]) if item.get('type')=='text')+json.dumps(result.get('structuredContent',{}))
    try:
        await supervisor.warmup()
        schema={item['name']:item['parameters'] for item in supervisor.catalogue}
        upstream_session=None
        async def call(name,arguments,pause=False):
            nonlocal paused
            if 'session_id' in schema[name].get('properties',{}):arguments={**arguments,'session_id':upstream_session}
            started=await supervisor.call('serena_operation_start',{'tool':name,'arguments':arguments},permit())
            operation=started['structuredContent']['operation_id']
            if pause:
                await asyncio.sleep(6)
                assert supervisor.lease.paused
                states=[]
                for path in Path('/proc').iterdir():
                    if not path.name.isdecimal():continue
                    try:status=dict(line.split(':',1) for line in (path/'status').read_text().splitlines() if ':' in line)
                    except (OSError,ValueError):continue
                    if status.get('Uid','').split()[:1]==['1000']:states.append(status['State'].strip().split()[0])
                assert states and all(state.upper()=='T' for state in states),states
                paused=True
            for attempt in range(60):
                result=await supervisor.call('serena_operation_poll',{'operation_id':operation,'tool':name},permit())
                value=result['structuredContent']
                if value['state'] in {'completed','failed'}:
                    actual=value.get('result',{})
                    assert actual and not actual.get('isError'),(name,value['state'],text(actual)[-1000:])
                    return actual
                assert value['state']=='running',value
                await asyncio.sleep(1)
            raise TimeoutError('Bounded native operation did not finish')
        stage='instructions'
        instructions=await call('initial_instructions',{})
        match=re.search(r'session id is [`]?([0-9a-f]+)',text(instructions))
        assert match
        upstream_session=match.group(1)
        stage='activation';await call('activate_project',{'project':'Briareus project'})
        library,application=('library.ts','application.ts') if language=='typescript' else ('library.hpp','application.cpp')
        stage='overview'
        assert 'Greeter' in text(await call('get_symbols_overview',{'relative_path':library,'depth':1},pause=True))
        stage='symbol'
        assert 'return701;' in text(await call('find_symbol',{'name_path_pattern':'Greeter/greet','relative_path':library,'include_body':True})).replace(' ','')
        stage='references'
        assert application in text(await call('find_referencing_symbols',{'name_path':'Greeter','relative_path':library}))
        stage='edit'
        body='greet(): number {\n    return 709;\n}' if language=='typescript' else 'int greet() const {\n    return 709;\n}'
        await call('replace_symbol_body',{'name_path':'Greeter/greet','relative_path':library,'body':body})
        stage='rename'
        await call('rename_symbol',{'name_path':'Greeter','relative_path':library,'new_name':'Welcomer'})
        await supervisor.close()
        check="from pathlib import Path;import sys,shutil;p=Path('/project-data')/sys.argv[1];a=(p/sys.argv[2]).read_text();b=(p/sys.argv[3]).read_text();assert 'return 709;' in a and 'Welcomer' in a and 'Welcomer' in b and 'Greeter' not in b;shutil.rmtree(p)"
        await helper(check,relative,library,application)
        print(json.dumps({'native_deferred_lsp':language,'semantic_workflow':'passed','uid_cohort_paused_after_expiry':paused,'owned_fixture_deleted':True}),flush=True)
    except Exception as error:
        print(json.dumps({'native_deferred_lsp':language,'stage':stage,'outcome':'failed','error_type':type(error).__name__,'error':str(error)[-1200:]}),flush=True)
        raise
    finally:await supervisor.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('language',choices=['typescript','cpp'])
    asyncio.run(main(parser.parse_args().language))
