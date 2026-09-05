import importlib.util,sys,time,statistics
from pathlib import Path
root=Path('C:/dev/AppData/Local/hermes/hermes-agent');sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('plugin',root.parent/'plugins/toolrush/__init__.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
from tools.environments.local import LocalEnvironment
from tools.toolrush_shell import WarmHandle
samples={}
def clock(cls,name):
 real=getattr(cls,name)
 def timed(*a,**kw):
  start=time.perf_counter()
  try:return real(*a,**kw)
  finally:samples.setdefault(name,[]).append((time.perf_counter()-start)*1000)
 setattr(cls,name,timed)
for c,n in [(LocalEnvironment,'_wrap_command'),(LocalEnvironment,'_run_bash'),(LocalEnvironment,'_wait_for_process'),(WarmHandle,'_run')]:clock(c,n)
e=LocalEnvironment(str(root))
try:
 for _ in range(12):e.execute('printf proof')
finally:e.cleanup()
print({k:[round(x,3) for x in v] for k,v in samples.items()})
