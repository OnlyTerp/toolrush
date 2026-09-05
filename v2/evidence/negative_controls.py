"""Disposable process controls: sabotage real functions without disk edits."""
import hashlib,json,os,sys,subprocess
from pathlib import Path
ROOT=Path('C:/dev/AppData/Local/hermes/hermes-agent'); OUT=Path('C:/dev/.operator/toolrush-v2');sys.path.insert(0,str(ROOT))
files=['tools/file_operations.py','tools/file_tools.py','tools/toolrush_rg.py','tools/toolrush_shell.py','tools/toolrush_rpc.py','tools/code_execution_tool.py','tools/code_kernel.py','agent/toolrush_admission.py']
before={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}
cases={
 'read-disabled':("from tools import toolrush_runtime as m; m.enabled=lambda *a:False",['tests/tools/test_toolrush_native_read.py::test_windows_read_handler_uses_native_bytes']),
 'search-disabled':("from tools.file_operations import ShellFileOperations as C; C._native_rg_context=lambda self:None",['tests/tools/test_toolrush_native_search.py::test_real_search_runs_rg_without_shell']),
 'rpc-serialized':("from tools import toolrush_rpc as m; m.MAX_WORKERS=1",['tests/tools/test_toolrush_rpc.py::test_parallel_client_real_socket_overlaps_and_keeps_order']),
 'unsafe-admission':("from agent import toolrush_admission as m; m.readonly=lambda command:True",['tests/run_agent/test_toolrush_admission_safety.py']),
 'no-snapshot-commit':("from tools import toolrush_shell as m; m.os.replace=lambda *a:None",['tests/tools/test_toolrush_plugin_v2.py::test_loaded_plugin_exports_exitcodes_and_output']),
}
if len(sys.argv)>1:
 key=sys.argv[1];code,tests=cases[key];exec(code);import pytest;sys.exit(pytest.main(tests+['-q','--tb=short','--junitxml='+str(OUT/f'negative-{key}.xml')]))
records=[]
for key in cases:
 r=subprocess.run([sys.executable,__file__,key],cwd=ROOT,capture_output=True)
 (OUT/f'negative-{key}.log').write_bytes(r.stdout+r.stderr)
 records.append({'name':key,'exit_code':r.returncode})
 print(key,r.returncode)
assert all(r['exit_code']==1 for r in records),records
import xml.etree.ElementTree as E
for record in records:
 failures=[case for case in E.parse(OUT/('negative-'+record['name']+'.xml')).findall('.//testcase') if case.find('failure') is not None]
 assert failures,record
 record['assertion_failures']=[case.attrib.get('name') for case in failures]
 if record['name']=='no-snapshot-commit':
  messages=' '.join(case.find('failure').attrib.get('message','') for case in failures)
  assert 'value0' in messages,messages # reject unrelated compatibility failure
after={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}
assert after==before,'installed files changed during disposable controls'
(OUT/'negative-controls.json').write_text(json.dumps({'controls':records,'unchanged_hashes':after},indent=2))
