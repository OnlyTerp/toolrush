"""Function-scoped update survival; no stale whole-module restoration."""
import importlib.util,json,sys,types
from pathlib import Path
import pytest
PLUGIN=Path('C:/dev/AppData/Local/hermes/plugins/toolrush')

def load():
 spec=importlib.util.spec_from_file_location('tr_compat_test',PLUGIN/'compat.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def case():
 m=types.ModuleType('tr_target_test');m.marker='preserved'
 before='def value(x=1):\n    return x + 1\n'
 after='def value(x=1):\n    return x + 2\n'
 exec(before,m.__dict__);sys.modules[m.__name__]=m
 return m,before,after

def test_compat_preserves_existing_function_references():
 c=load();m,b,a=case();old_reference=m.value
 rows=[{'module':m.__name__,'qualname':'value','before':b,'after':a}]
 c.install_rows(rows)
 assert m.value is old_reference and old_reference()==3
 assert m.marker=='preserved'
 c.install_rows(rows)
 assert old_reference()==3

def test_compat_refuses_entire_lane_on_unknown_signature():
 c=load();m,b,a=case();original=m.value
 rows=[{'module':m.__name__,'qualname':'value','before':b,'after':a},
       {'module':m.__name__,'qualname':'marker','before':b,'after':a}]
 with pytest.raises(c.CompatibilityError):c.install_rows(rows)
 assert m.value is original and m.value()==2

def test_compat_new_function_uses_live_module_globals():
 c=load();m,b,a=case();m.DYNAMIC=2
 row={'module':m.__name__,'qualname':'fresh','before':None,'after':'def fresh():\n    return DYNAMIC\n'}
 c.install_rows([row]);m.DYNAMIC=9
 assert m.fresh()==9


def test_doctor_smoke_restores_known_preupdate_rpc_in_fresh_process(tmp_path):
 import subprocess
 script=tmp_path/'doctor_update_probe.py'
 root=PLUGIN.parent.parent/'hermes-agent'
 script.write_text('''import sys,json,importlib,importlib.util,runpy
from pathlib import Path
R=Path('''+repr(str(root))+''');P=Path('''+repr(str(PLUGIN))+''')
sys.path.insert(0,str(R))
s=importlib.util.spec_from_file_location('compat_control',P/'compat.py');c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
payload=json.loads((P/'payload.json').read_text())
for row in payload['lanes']['rpc']:
 module=importlib.import_module(row['module']);owner=module;parts=row['qualname'].split('.')
 for part in parts[:-1]:owner=getattr(owner,part)
 if row['before'] is None:delattr(owner,parts[-1])
 else:
  original=c.compile_function(row['before'],module,parts[-1]);current=getattr(owner,parts[-1])
  current.__code__=original.__code__;current.__defaults__=original.__defaults__;current.__kwdefaults__=original.__kwdefaults__
sys.argv=[str(P/'doctor.py'),'--smoke']
runpy.run_path(str(P/'doctor.py'),run_name='__main__')
''',encoding='utf-8')
 result=subprocess.run([sys.executable,str(script)],cwd=str(root),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=90)
 assert result.returncode==0,result.stdout
 assert 'TOOLRUSH-DOCTOR-OK' in result.stdout,result.stdout


def test_compat_source_hash_mismatch():
 c=load()
 with pytest.raises(c.CompatibilityError):c.verify_blob(b'changed','not-a-hash')
