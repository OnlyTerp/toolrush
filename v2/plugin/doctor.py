"""Read-only ToolRush installed integrity and compatibility check. No models."""
import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

P=Path(__file__).parent
R=P.parent.parent/'hermes-agent'
sys.path.insert(0,str(R))
parser=argparse.ArgumentParser();parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
s=importlib.util.spec_from_file_location('toolrush_doctor_compat',P/'compat.py');c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
payload=json.loads((P/'payload.json').read_text())
result={'payload':{},'lanes':{},'restart_note':'This fresh-process check does not activate already-running gateways.'}
try:
 for name,row in payload['helpers'].items():
  c.verify_blob((P/row['file']).read_bytes(),row['sha256']);result['payload'][name]='verified'
 for lane,rows in payload['lanes'].items():
  try: result['lanes'][lane]={'status':'compatible','pending_function_patches':len(c.prepare_rows(rows))}
  except Exception as exc:result['lanes'][lane]={'status':'degraded','reason':str(exc)}
 if args.smoke:
  # A compatible upstream update may have removed the in-tree patches.
  # Exercise the real plugin boot before the real RPC smoke, in THIS fresh
  # process only. Existing gateways and on-disk source remain untouched.
  from hermes_cli.plugins import PluginManager,PluginManifest
  manager=PluginManager()
  manager._load_plugin(PluginManifest(name='toolrush',version='2.0.0',source='user',path=str(P),key='toolrush'))
  loaded=manager._plugins['toolrush']
  assert loaded.enabled and not loaded.error,loaded.error
  status=loaded.module._COMPAT_STATUS
  assert set(status)=={'files','rpc','admission','snapshot'} and all(x['status']=='ready' for x in status.values()),status
  result['boot']=status
  from tools.code_execution_tool import execute_code
  from tools.code_kernel import shutdown_all_kernels
  code='from hermes_tools import parallel\nr = parallel('+repr([{'tool':'read_file','args':{'path':str(R/f),'limit':4}} for f in ['tools/file_tools.py','tools/file_operations.py']])+')\nassert len(r)==2 and all("content" in x for x in r), r\nprint("TOOLRUSH-DOCTOR-OK")'
  try:
   output=json.loads(execute_code(code,task_id='toolrush-doctor',enabled_tools=['read_file']))
   result['smoke']={'exit_code':output.get('exit_code'),'output':output.get('output'),'tool_calls':output.get('tool_calls_made')}
   assert output.get('exit_code')==0 and output.get('tool_calls_made')==2,output
  finally:shutdown_all_kernels()
 result['ok']=all(v['status']=='compatible' for v in result['lanes'].values())
except Exception as exc:
 result['ok']=False;result['error']=str(exc)
print(json.dumps(result,indent=2));sys.exit(0 if result['ok'] else 2)
