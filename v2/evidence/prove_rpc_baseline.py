"""Run the two known RPC neighbor failures with original functions in memory."""
import importlib,importlib.util,json,sys
from pathlib import Path
R=Path('C:/dev/AppData/Local/hermes/hermes-agent');P=R.parent/'plugins/toolrush';W=Path(__file__).parent;sys.path.insert(0,str(R))
s=importlib.util.spec_from_file_location('tr_rpc_control',P/'compat.py');c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
payload=json.loads((P/'payload.json').read_text())
for row in payload['lanes']['rpc']:
 if row['before'] is None:continue
 module=importlib.import_module(row['module']);target=module;parts=row['qualname'].split('.')
 for part in parts[:-1]:target=getattr(target,part)
 baseline=c.compile_function(row['before'],module,parts[-1]);current=getattr(target,parts[-1]);current.__code__=baseline.__code__;current.__defaults__=baseline.__defaults__;current.__kwdefaults__=baseline.__kwdefaults__
import pytest
sys.exit(pytest.main(['tests/tools/test_code_execution.py::TestRpcTokenAuthorization::test_missing_token_rejected','tests/tools/test_code_kernel.py::TestKernelOwnershipAndLifecycle::test_parallel_cells_share_one_kernel_process','-q','--tb=short','--junitxml='+str(W/'rpc-baseline-control.xml')]))
