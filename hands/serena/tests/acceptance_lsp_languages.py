"""Actual bundled TypeScript/clangd semantic editing, in a disposable offline image.

This native probe is not evidence of Rauthy/Cedar admission. It writes only its
own UUID fixture under /project-data; it never mounts a host project workspace.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from uuid import uuid4

from acceptance_lsp import text


def fixture(project,language):
    if language=='typescript':
        library,application='library.ts','application.ts'
        (project/library).write_text('export class Greeter {\n  greet(): number { return 701; }\n}\n')
        (project/application).write_text("import { Greeter } from './library';\nexport function render(): number { return new Greeter().greet(); }\n")
        (project/'tsconfig.json').write_text(json.dumps({'compilerOptions':{
            'target':'ES2020','module':'CommonJS','strict':True,'noEmit':True},'include':['*.ts']}))
        body='greet(): number {\n    return 709;\n}'
    else:
        library,application='library.hpp','application.cpp'
        (project/library).write_text('#pragma once\nclass Greeter {\npublic:\n  int greet() const { return 701; }\n};\n')
        (project/application).write_text('#include "library.hpp"\nint render() { Greeter g; return g.greet(); }\n')
        (project/'compile_commands.json').write_text(json.dumps([{'directory':str(project),
            'file':str(project/application),'arguments':['clang++','-std=c++17','-I'+str(project),'-c',str(project/application)]}]))
        body='int greet() const {\n    return 709;\n}'
    return library,application,body


async def main(language):
    relative='.serena-'+language+'-'+uuid4().hex
    project=Path('/project-data')/relative
    project.mkdir(mode=0o700)
    library,application,body=fixture(project,language)
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','serena_hand.isolated_child',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        env=dict(os.environ,BRIAREUS_SERENA_PROJECT_PATH=relative,SERENA_HOME='/home/hand/.serena'),
        cwd='/app/src',limit=1000001)
    stage='startup'
    try:
        raw=await asyncio.wait_for(process.stdout.readline(),180)
        if not raw:raise RuntimeError('Serena metadata unavailable: '+(await process.stderr.read()).decode(errors='replace')[-1500:])
        metadata=json.loads(raw)
        assert metadata['ready'] is True
        catalogue={tool['name']:tool for tool in metadata['tools']}
        session=None
        async def call(name,arguments):
            if 'session_id' in catalogue[name]['parameters'].get('properties',{}):
                assert session
                arguments={**arguments,'session_id':session}
            operation=str(uuid4())
            process.stdin.write(json.dumps({'id':operation,'tool':name,'arguments':arguments,'expires_at':time.time()+5}).encode()+b'\n')
            await process.stdin.drain()
            reply=json.loads(await asyncio.wait_for(process.stdout.readline(),7))
            assert reply['id']==operation
            assert not reply['result'].get('isError'),(name,text(reply['result'])[-1200:])
            return reply['result']
        stage='instructions'
        initial=await call('initial_instructions',{})
        match=re.search(r'session id is [`]?([0-9a-f]+)',text(initial))
        if match:session=match.group(1)
        stage='activate'
        await call('activate_project',{'project':'Briareus project'})
        stage='overview'
        overview=await call('get_symbols_overview',{'relative_path':library,'depth':1})
        assert 'Greeter' in text(overview)
        stage='symbol'
        symbol=await call('find_symbol',{'name_path_pattern':'Greeter/greet','relative_path':library,'include_body':True})
        assert 'return701;' in text(symbol).replace(' ','')
        stage='references'
        references=await call('find_referencing_symbols',{'name_path':'Greeter','relative_path':library})
        assert application in text(references)
        stage='body_edit'
        await call('replace_symbol_body',{'name_path':'Greeter/greet','relative_path':library,'body':body})
        assert 'return 709;' in (project/library).read_text()
        stage='rename'
        await call('rename_symbol',{'name_path':'Greeter','relative_path':library,'new_name':'Welcomer'})
        assert 'Welcomer' in (project/library).read_text()
        assert 'Welcomer' in (project/application).read_text()
        assert 'Greeter' not in (project/application).read_text()
        print(json.dumps({'native_lsp':language,'workflow':'activate/overview/body/references/edit/cross-file-rename','outcome':'passed'}),flush=True)
    except Exception as error:
        try:diagnostics=(await asyncio.wait_for(process.stderr.read(20000),0.2)).decode(errors='replace')[-2500:]
        except TimeoutError:diagnostics=''
        print(json.dumps({'native_lsp':language,'stage':stage,'outcome':'failed','error_type':type(error).__name__,
                          'error':str(error)[-1800:],'diagnostics':diagnostics}),flush=True)
        raise
    finally:
        if process.returncode is None:process.terminate()
        try:await asyncio.wait_for(process.wait(),5)
        except TimeoutError:
            process.kill();await process.wait()
        shutil.rmtree(project)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('language',choices=['typescript','cpp'])
    asyncio.run(main(parser.parse_args().language))
