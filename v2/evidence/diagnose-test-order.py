"""Bounded diagnosis for full-suite native lane disablement; no disk patch."""
import sys,os,traceback
from pathlib import Path
R=Path('C:/dev/AppData/Local/hermes/hermes-agent');sys.path.insert(0,str(R))
import tools.toolrush_runtime as runtime
original=runtime.enabled

def traced(key,legacy_env=''):
 result=original(key,legacy_env)
 if not result:
  print('GATE-OFF',key,legacy_env,os.environ.get(legacy_env),'HERMES_HOME',os.environ.get('HERMES_HOME'),flush=True)
  try:
   from hermes_cli.config import load_config_readonly
   c=load_config_readonly();print('CONFIG',type(c),repr(c.get('toolrush','ABSENT')),flush=True)
  except Exception:traceback.print_exc()
 return result
runtime.enabled=traced
from tools.file_operations import ShellFileOperations
local_original=ShellFileOperations._lsp_local_only
def local_trace(self):
 result=local_original(self)
 if not result:
  import tools.environments.local as local
  print('LOCAL-MISMATCH',type(self.env),id(type(self.env)),local.LocalEnvironment,id(local.LocalEnvironment),flush=True)
 return result
ShellFileOperations._lsp_local_only=local_trace
import pytest
sys.exit(pytest.main(['tests/run_agent/test_parallel_terminal_and_wire.py','tests/run_agent/test_tool_batch_segmentation.py','tests/run_agent/test_toolrush_admission_safety.py','tests/tools/test_toolrush_native_read.py::test_windows_read_handler_uses_native_bytes','-s','-q','--tb=short']))
