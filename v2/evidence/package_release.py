"""Snapshot only ToolRush v2 artifacts; no secrets/config/state/whole checkout."""
import hashlib,json,shutil,zipfile
from pathlib import Path
R=Path('C:/dev/AppData/Local/hermes/hermes-agent');P=R.parent/'plugins/toolrush';W=Path(__file__).parent;D=Path('C:/dev/toolrush/v2')
D.mkdir(parents=True,exist_ok=True)
source=['tools/file_operations.py','tools/file_tools.py','tools/code_execution_tool.py','tools/code_kernel.py','tools/environments/base.py','agent/tool_dispatch_helpers.py','agent/toolrush_admission.py','tools/toolrush_runtime.py','tools/toolrush_rg.py','tools/toolrush_shell.py','tools/toolrush_rpc.py']
tests=[str(p.relative_to(R)).replace('\\','/') for p in (R/'tests').rglob('test_toolrush*.py')]
tests+=['tests/run_agent/test_parallel_terminal_and_wire.py','tests/run_agent/test_tool_batch_segmentation.py','tests/tools/test_file_tools.py','tests/tools/test_search_files_engine_selection.py','tests/tools/test_search_zero_match_and_multipath.py']
for f in sorted(set(source+tests)):
 dst=D/'installed-source'/f;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(R/f,dst)
for f in P.rglob('*'):
 if f.is_file() and '__pycache__' not in f.parts:
  dst=D/'plugin'/f.relative_to(P);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dst)
for f in W.iterdir():
 if f.is_file() and f.suffix in ('.md','.json','.xml','.py'):
  dst=D/'evidence'/f.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dst)
for sub in ('baseline','reviewer-final'):
 for f in (W/sub).rglob('*'):
  if f.is_file() and f.suffix in ('.py','.json','.xml','.md'):
   dst=D/'evidence'/f.relative_to(W);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dst)
shutil.copyfile(W/'report.md',D/'README.md')
manifest={str(f.relative_to(D)).replace('\\','/'):{'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in D.rglob('*') if f.is_file() and f.name!='MANIFEST.json'}
(D/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
archive=W/'ToolRush-v2.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for f in D.rglob('*'):
  if f.is_file():z.write(f,str(f.relative_to(D)))
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 for name,row in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==row['sha256']
print(json.dumps({'bundle':str(D),'files':len(manifest),'zip':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'verified':True},indent=2))
