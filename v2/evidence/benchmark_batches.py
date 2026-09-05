"""Real RPC+dispatch paired benchmark; controlled I/O wait labeled separately."""
import json,os,sys,socket,threading,time,statistics,math,uuid
from pathlib import Path
ROOT=Path('C:/dev/AppData/Local/hermes/hermes-agent');OUT=Path('C:/dev/.operator/toolrush-v2');sys.path.insert(0,str(ROOT))
from tools.code_execution_tool import _rpc_server_loop,generate_hermes_tools_module
import model_tools
from tools import file_tools as ft
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.toolrush_runtime import enabled
import importlib.util
spec=importlib.util.spec_from_file_location('toolrush_batch_bench',ROOT.parent/'plugins/toolrush/__init__.py');plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
server=socket.socket();server.bind(('127.0.0.1',0));server.listen(); stop=threading.Event();counter=[0];log=[]
os.environ['HERMES_RPC_SOCKET']='tcp://127.0.0.1:'+str(server.getsockname()[1]);os.environ['HERMES_RPC_TOKEN']='bench-token'
env=LocalEnvironment(str(ROOT));ops=ShellFileOperations(env);original_ops=ft._get_file_ops;ft._get_file_ops=lambda task_id='default':ops
controlled_delay=[False]
def dispatch(name,args):
 if controlled_delay[0]:time.sleep(.05)
 return model_tools.handle_function_call(name,args,task_id='trbench-'+uuid.uuid4().hex)
th=threading.Thread(target=_rpc_server_loop,args=(server,'bench',log,counter,10000,frozenset({'read_file','search_files'}),stop,'bench-token'),kwargs={'dispatch':dispatch},daemon=True);th.start()
client={};exec(generate_hermes_tools_module(['read_file','search_files']),client)
paths=[ROOT/p for p in ['tools/file_tools.py','tools/file_operations.py','tools/code_execution_tool.py','tools/code_kernel.py']]
workloads={
 'four_reads':[{'tool':'read_file','args':{'path':str(p),'offset':30,'limit':60}} for p in paths],
 'four_searches':[{'tool':'search_files','args':{'pattern':'def ','path':p.as_posix(),'limit':20}} for p in paths],
 'mixed':[{'tool':('read_file' if i%2==0 else 'search_files'),'args':({'path':str(p),'limit':60} if i%2==0 else {'pattern':'def ','path':p.as_posix(),'limit':20})} for i,p in enumerate(paths)],
 'controlled_50ms_io_plus_real_reads':[{'tool':'read_file','args':{'path':str(p),'offset':30,'limit':60}} for p in paths],
}
results={}
try:
 for name,calls in workloads.items():
  controlled_delay[0]=name.startswith('controlled')
  times={'sequential':[],'parallel':[]}; reference=None
  for i in range(13):
   for lane in (['sequential','parallel'] if i%2==0 else ['parallel','sequential']):
    start=time.perf_counter()
    value=client['parallel'](calls) if lane=='parallel' else [client['_call'](c['tool'],c['args']) for c in calls]
    times[lane].append((time.perf_counter()-start)*1000)
    assert all(isinstance(r,dict) and 'error' not in r for r in value),value
    if reference is None:reference=value
    assert value==reference,(name,lane,value)
  def stats(v):
   warm=v[1:];return {'first_ms':v[0],'n':len(warm),'median_ms':statistics.median(warm),'p95_ms':sorted(warm)[math.ceil(.95*len(warm))-1],'samples_ms':v}
  results[name]={k:stats(v) for k,v in times.items()};results[name]['speedup']=results[name]['sequential']['median_ms']/results[name]['parallel']['median_ms'];results[name]['parity']=True
  print(name,results[name]['speedup'])
 (OUT/'benchmark-batches.json').write_text(json.dumps({'real_handlers':True,'controlled_delay_labeled':True,'counter':counter[0],'results':results},indent=2))
finally:
 stop.set();client['_sock'].close();server.close();th.join(3);ft._get_file_ops=original_ops;env.cleanup()
