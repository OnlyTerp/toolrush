"""Profile real local tools; no models or external network calls."""
import cProfile
import io
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import time

ROOT = Path('C:/dev/AppData/Local/hermes/hermes-agent')
OUT = Path('C:/dev/.operator/toolrush-v2')
sys.path.insert(0, str(ROOT))
from tools import file_tools as ft
from tools.environments.local import _msys_to_windows_path, _make_run_env

ops = ft._get_file_ops('toolrush-v2-profile')
rg = ops._resolve_command('rg')
rg = _msys_to_windows_path(rg)
file = str(ROOT/'tools/file_operations.py').replace('\\','/')
tree = str(ROOT/'tools').replace('\\','/')
results = {'rg': rg, 'file': file, 'tree': tree, 'environment': type(ops.env).__name__, 'samples': {}}

def clean():
    with ft._read_tracker_lock:
        ft._read_tracker.pop('toolrush-v2-profile', None)

def read():
    clean()
    return ft.read_file_tool(file, offset=1, limit=100, task_id='toolrush-v2-profile')

def search(lane):
    os.environ['TOOLRUSH_SEARCH'] = lane
    clean()
    return ft.search_tool('def read_file', path=tree, file_glob='file_operations.py', limit=20, task_id='toolrush-v2-profile')

def direct_rg():
    r = subprocess.run([rg, '--line-number','--no-heading','--with-filename','--max-columns','2000','--max-columns-preview','--glob','file_operations.py','def read_file',tree], cwd=ops.env.cwd, env=_make_run_env(ops.env.env), stdin=subprocess.DEVNULL, capture_output=True)
    assert r.returncode in (0,1), r.stderr
    return r.stdout

for name, fn in [('read_handler',read), ('search_old_fast',lambda: search('1')), ('search_shell_rg',lambda:search('0')), ('direct_rg_transport',direct_rg), ('existing_native_read',lambda:ops._read_file_native(file,1,100))]:
    samples=[]
    for _ in range(7):
        t=time.perf_counter(); value=fn(); samples.append((time.perf_counter()-t)*1000)
        if isinstance(value,str):
            body=json.JSONDecoder().raw_decode(value)[0]
            assert not body.get('error'), body
    results['samples'][name]={'ms':samples,'median_ms':statistics.median(samples[1:]),'first_ms':samples[0]}
    prof=cProfile.Profile(); prof.runcall(fn)
    sio=io.StringIO(); pstats.Stats(prof,stream=sio).sort_stats('cumulative').print_stats(35)
    (OUT/(name+'.profile.txt')).write_text(sio.getvalue(),encoding='utf-8')
    print(name,results['samples'][name],flush=True)
(OUT/'findings-baseline.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('PROFILE_COMPLETE')
