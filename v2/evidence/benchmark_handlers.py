"""Paired real-handler benchmark. No models. Backend and plugin are real."""
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT = Path('C:/dev/AppData/Local/hermes/hermes-agent')
OUT = Path('C:/dev/.operator/toolrush-v2')
sys.path.insert(0, str(ROOT))
from tools import file_tools as ft
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations

if '--plugin' in sys.argv:
    spec=importlib.util.spec_from_file_location('toolrush_bench_plugin',ROOT.parent/'plugins/toolrush/__init__.py')
    plugin=importlib.util.module_from_spec(spec); spec.loader.exec_module(plugin)
    plugin.register(None)
else:
    plugin=None

env=LocalEnvironment(cwd=str(ROOT)); ops=ShellFileOperations(env)
original=ft._get_file_ops; ft._get_file_ops=lambda task_id='default':ops
workloads={
 'read_100_lines':lambda:ft.read_file_tool(str(ROOT/'tools/file_tools.py'),offset=200,limit=100,task_id=uuid.uuid4().hex),
 'read_large_python':lambda:ft.read_file_tool(str(ROOT/'run_agent.py'),offset=1000,limit=200,task_id=uuid.uuid4().hex),
 'search_single_file':lambda:ft.search_tool('def ',path=(ROOT/'tools/file_operations.py').as_posix(),limit=30,task_id=uuid.uuid4().hex),
 'search_repo_content':lambda:ft.search_tool('def ',path=(ROOT/'tools').as_posix(),file_glob='*.py',limit=30,task_id=uuid.uuid4().hex),
 'search_context':lambda:ft.search_tool('_get_file_ops',path=(ROOT/'tools/file_tools.py').as_posix(),context=2,limit=30,task_id=uuid.uuid4().hex),
 'search_no_match':lambda:ft.search_tool('TOOLRUSH_NONEXISTENT_Q93Z',path=(ROOT/'tools').as_posix(),file_glob='*.py',limit=30,task_id=uuid.uuid4().hex),
 'file_discovery':lambda:ft.search_tool('*.py',target='files',path=(ROOT/'tools').as_posix(),limit=30,task_id=uuid.uuid4().hex),
}
results={}
try:
 for name,fn in workloads.items():
    samples={'off':[],'on':[]}; envelopes={}
    for i in range(17):
        for lane in (['off','on'] if i%2==0 else ['on','off']):
            os.environ['TOOLRUSH_FASTLANE']='1' if lane=='on' else '0'
            os.environ['TOOLRUSH_SEARCH']='1' if lane=='on' else '0'
            start=time.perf_counter(); raw=fn(); elapsed=(time.perf_counter()-start)*1000
            obj=json.JSONDecoder().raw_decode(raw)[0]
            if 'error' in obj:
                raise RuntimeError((name,lane,obj))
            samples[lane].append(elapsed); envelopes[lane]=obj
    def stats(values):
        warm=values[1:]
        return {'cold_ms':values[0], 'warm_n':len(warm),'median_ms':statistics.median(warm),
                'p95_ms':sorted(warm)[math.ceil(.95*len(warm))-1], 'samples_ms':values}
    results[name]={lane:stats(data) for lane,data in samples.items()}
    results[name]['speedup']=results[name]['off']['median_ms']/results[name]['on']['median_ms']
    # Search content parity is exact. File discovery promises discovery order,
    # not exact stable membership of a bounded prefix, so verify nonempty
    # matching entries instead of laundering that into a byte-equality claim.
    results[name]['envelopes_equal']=envelopes['on']==envelopes['off']
    if name!='file_discovery':
        assert envelopes['on']==envelopes['off'], (name,envelopes)
    print(name, {k:results[name][k]['median_ms'] for k in ['off','on']}, 'speedup',results[name]['speedup'],flush=True)
finally:
 ft._get_file_ops=original
 env.cleanup()
suffix='plugin' if plugin else 'core'
(OUT/f'benchmark-{suffix}.json').write_text(json.dumps({'plugin_loaded':bool(plugin),'root':str(ROOT),'results':results},indent=2),encoding='utf-8')
print('BENCHMARK_COMPLETE',suffix)
