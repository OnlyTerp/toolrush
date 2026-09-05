"""Load only ToolRush through Hermes's installed PluginManager; no providers."""
import json,os,sys
from pathlib import Path
R=Path('C:/dev/AppData/Local/hermes/hermes-agent');P=R.parent/'plugins/toolrush';W=Path(__file__).parent
sys.path.insert(0,str(R))
from hermes_cli.plugins import PluginManager,PluginManifest
from hermes_cli.config import load_config_readonly
from tools.environments.local import LocalEnvironment
from tools.code_kernel import shutdown_all_kernels
from tools.code_execution_tool import execute_code
assert 'toolrush' in load_config_readonly().get('plugins',{}).get('enabled',[])
manager=PluginManager()
manifest=PluginManifest(name='toolrush',version='2.0.0',source='user',path=str(P),key='toolrush')
manager._load_plugin(manifest)
loaded=manager._plugins['toolrush'];assert loaded.enabled and not loaded.error,loaded.error
status=loaded.module._COMPAT_STATUS
assert set(status)=={'files','rpc','admission','snapshot'} and all(x['status']=='ready' for x in status.values()),status
assert getattr(LocalEnvironment._run_bash,'_toolrush_v2',False)
env=LocalEnvironment(cwd=str(R))
try:
 first=env.execute('export TOOLRUSH_BOOT_PROOF=preserved',timeout=5)
 second=env.execute('printf "%s" "$TOOLRUSH_BOOT_PROOF"',timeout=5)
 assert first['returncode']==second['returncode']==0 and 'preserved' in second['output'],(first,second)
 code='from hermes_tools import parallel\nr=parallel('+repr([{'tool':'read_file','args':{'path':str(R/f),'limit':4}} for f in ['tools/file_operations.py','tools/file_tools.py']])+')\nassert len(r)==2 and all("content" in x for x in r),r\nprint("TOOLRUSH-BOOT-OK")'
 output=json.loads(execute_code(code,task_id='toolrush-boot-proof',enabled_tools=['read_file']))
 assert output['exit_code']==0 and output['tool_calls_made']==2 and 'TOOLRUSH-BOOT-OK' in output['output'],output
 result={'loader':'installed PluginManager._load_plugin','enabled':loaded.enabled,'lanes':status,'warm_export_roundtrip':True,'rpc':{k:output[k] for k in ['exit_code','output','tool_calls_made']},'existing_gateway_restarted':False}
 (W/'boot-proof.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
finally:
 env.cleanup();shutdown_all_kernels()
