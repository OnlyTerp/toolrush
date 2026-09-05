"""Simulate upstream reverting ToolRush functions IN MEMORY, never on disk."""
import hashlib,importlib,importlib.util,json,os,sys
from pathlib import Path
R=Path('C:/dev/AppData/Local/hermes/hermes-agent');P=R.parent/'plugins/toolrush';W=Path(__file__).parent;sys.path.insert(0,str(R))
spec=importlib.util.spec_from_file_location('tr_update_compat',P/'compat.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
payload=json.loads((P/'payload.json').read_text())
paths=sorted({row['module'].replace('.','/')+'.py' for rows in payload['lanes'].values() for row in rows})
before={f:hashlib.sha256((R/f).read_bytes()).hexdigest() for f in paths}
for lane,rows in payload['lanes'].items():
 for row in rows:
  module=importlib.import_module(row['module']);target=module;parts=row['qualname'].split('.')
  for part in parts[:-1]:target=getattr(target,part)
  if row['before'] is None:delattr(target,parts[-1]);continue
  original=c.compile_function(row['before'],module,parts[-1]);current=getattr(target,parts[-1]);current.__code__=original.__code__;current.__defaults__=original.__defaults__;current.__kwdefaults__=original.__kwdefaults__
  current._toolrush_installed_code=current.__code__;current._toolrush_source_digest=c.source_digest(row['before'])
print('SIMULATED_CORE_REVERSION', {k:len(v) for k,v in payload['lanes'].items()},flush=True)
status=c.install();print(json.dumps(status));assert all(v['status']=='ready' for v in status.values()),status
assert sum(v['patched'] for v in status.values())==sum(map(len,payload['lanes'].values()))
from tools import file_tools as ft
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
import uuid
ops=ShellFileOperations(LocalEnvironment(cwd=str(R)));old=ft._get_file_ops;ft._get_file_ops=lambda task_id='default':ops
try:
 read=json.loads(ft.read_file_tool(str(R/'tools/file_tools.py'),offset=1,limit=10,task_id=uuid.uuid4().hex));assert 'content' in read,read
 search=json.loads(ft.search_tool('def ',path=(R/'tools/file_tools.py').as_posix(),limit=2,task_id=uuid.uuid4().hex));assert search.get('truncated'),search
 from tools.code_execution_tool import generate_hermes_tools_module
 assert 'def parallel(' in generate_hermes_tools_module(frozenset({'read_file'}))
finally:ft._get_file_ops=old;ops.env.cleanup()
after={f:hashlib.sha256((R/f).read_bytes()).hexdigest() for f in paths};assert before==after
result={'status':status,'installed_sources_unchanged':before==after,'read_search_generated_rpc_proven':True,'sha256':after}
(W/'update-simulation.json').write_text(json.dumps(result,indent=2));print('UPDATE_SURVIVAL_PROVEN')
