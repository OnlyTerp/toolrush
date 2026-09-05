"""Same-command terminal benchmark: stock, original plugin, repaired plugin."""
import importlib.util,json,os,statistics,sys,time,math
from pathlib import Path
ROOT=Path('C:/dev/AppData/Local/hermes/hermes-agent'); OUT=Path('C:/dev/.operator/toolrush-v2')
sys.path.insert(0,str(ROOT));mode=sys.argv[1]
from tools.environments.local import LocalEnvironment
if mode!='stock':
    path=OUT/'baseline/plugin/__init__.py' if mode=='old' else ROOT.parent/'plugins/toolrush/__init__.py'
    spec=importlib.util.spec_from_file_location('bench_toolrush',path);plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
    if mode=='new':
        status=plugin.register(None)
        assert getattr(LocalEnvironment._run_bash,'_toolrush_v2',False),status
os.environ['TOOLRUSH_PERSIST']='1'
e=LocalEnvironment(str(ROOT));samples={}; results={}
try:
    for name,cmd in [('builtin','printf TOOLRUSH_BENCH'),('python','python --version'),('git','git rev-parse --is-inside-work-tree')]:
        elapsed=[]
        for i in range(25):
            start=time.perf_counter();r=e.execute(cmd,timeout=20);elapsed.append((time.perf_counter()-start)*1000)
            assert r['returncode']==0,(mode,name,r)
            if name=='builtin':assert r['output']=='TOOLRUSH_BENCH',r
        warm=elapsed[1:];results[name]={'cold_ms':elapsed[0],'n':len(warm),'median_ms':statistics.median(warm),'p95_ms':sorted(warm)[math.ceil(.95*len(warm))-1],'samples_ms':elapsed}
    print(json.dumps({'mode':mode,'results':results},indent=2))
    (OUT/f'benchmark-terminal-{mode}.json').write_text(json.dumps({'mode':mode,'results':results},indent=2))
finally:e.cleanup()
