import json,sys,os,time,statistics
from pathlib import Path
ROOT=Path('C:/dev/AppData/Local/hermes/hermes-agent');OUT=Path('C:/dev/.operator/toolrush-v2');sys.path.insert(0,str(ROOT))
from tools.code_execution_tool import execute_code
from tools.code_kernel import shutdown_all_kernels
import importlib.util
spec=importlib.util.spec_from_file_location('toolrush_e2e',ROOT.parent/'plugins/toolrush/__init__.py');plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
# Real repository files; no fake data or provider calls.
files=[str(ROOT/p) for p in ['tools/file_tools.py','tools/file_operations.py','tools/code_execution_tool.py','tools/code_kernel.py']]
proof=f'''from hermes_tools import parallel
import json
r=parallel([{{"tool":"read_file","args":{{"path":p,"limit":20}}}} for p in {files!r}])
assert len(r)==4 and all("content" in x and x["content"] for x in r),r
print(json.dumps({{"count":len(r),"paths":[x.get("total_lines") for x in r],"proof":"TOOLRUSH-INSTALLED-E2E"}}))'''
try:
 result=json.loads(execute_code(proof,task_id='toolrush-v2-e2e',enabled_tools=['read_file']))
 (OUT/'installed-e2e.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result,indent=2))
 assert result.get('status')=='success' and result.get('tool_calls_made')==4,result
 assert 'TOOLRUSH-INSTALLED-E2E' in result.get('output',''),result
finally:shutdown_all_kernels()
