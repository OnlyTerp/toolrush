import sys,importlib.util,os,time,json,threading
from pathlib import Path
ROOT=Path('C:/dev/AppData/Local/hermes/hermes-agent');sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('plugin',ROOT.parent/'plugins/toolrush/__init__.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
from tools.environments.local import LocalEnvironment
from tools.toolrush_runtime import enabled
from tools.toolrush_shell import WarmHandle
os.environ['TOOLRUSH_PERSIST']='1'
e=LocalEnvironment(str(ROOT))
print('enabled',enabled('warm_shell','TOOLRUSH_PERSIST'),'class',e._run_bash.__module__)
r=e.execute('printf warm'); print('shell',getattr(e,'_toolrush_warm_v2',None),r)
h=e._run_bash("printf 'early-output'; sleep 1; printf 'finished'")
print('handle',type(h).__name__)
t=time.monotonic(); data=h.stdout.read(3); print('firstbytes',time.monotonic()-t,data); print(h.stdout.read());print(h.wait());e.cleanup()
