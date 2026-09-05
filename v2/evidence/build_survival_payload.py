"""Build reviewed function payloads, not full stale module copies."""
import ast,hashlib,json,shutil,subprocess,sys
from pathlib import Path
R=Path('C:/dev/AppData/Local/hermes/hermes-agent');W=Path(__file__).parent;P=R.parent/'plugins/toolrush'
def funcs(text):
 lines=text.splitlines(True);result={}
 def walk(nodes,prefix=''):
  for node in nodes:
   if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
    start=min([node.lineno]+[x.lineno for x in node.decorator_list])-1
    source=''.join(lines[start:node.end_lineno]);import textwrap
    result[prefix+node.name]=textwrap.dedent(source)
   elif isinstance(node,ast.ClassDef):walk(node.body,prefix+node.name+'.')
 walk(ast.parse(text).body);return result
lanes={
 'files':['tools/file_operations.py','tools/file_tools.py'],
 'rpc':['tools/code_execution_tool.py','tools/code_kernel.py'],
 'admission':['agent/tool_dispatch_helpers.py'],
 'snapshot':['tools/environments/base.py'],
}
helpers=['tools.toolrush_runtime','tools.toolrush_rg','tools.toolrush_shell','tools.toolrush_rpc','agent.toolrush_admission']
payload={'python':list(sys.version_info[:2]),'helpers':{},'lanes':{}}
for name in helpers:
 source=R/(name.replace('.','/')+'.py');target=P/'lib'/(name.replace('.','/')+'.py');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
 payload['helpers'][name]={'file':str(target.relative_to(P)).replace('\\','/'),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
for lane,files in lanes.items():
 rows=[]
 for f in files:
  baseline=W/'baseline'/f
  if baseline.exists():before=baseline.read_text(encoding='utf-8')
  else:
   result=subprocess.run(['git','show','HEAD:'+f],cwd=R,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True);before=result.stdout.decode('utf-8')
   baseline.parent.mkdir(parents=True,exist_ok=True);baseline.write_text(before,encoding='utf-8')
  b=funcs(before);a=funcs((R/f).read_text(encoding='utf-8'))
  for q,source in a.items():
   if b.get(q)==source:continue
   row={'module':f[:-3].replace('/','.'),'qualname':q,'before':b.get(q),'after':source}
   for field in ('before','after'):
    if row[field] is not None:row[field+'_sha256']=hashlib.sha256(row[field].encode()).hexdigest()
   rows.append(row)
 payload['lanes'][lane]=rows
(P/'payload.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
print({lane:len(rows) for lane,rows in payload['lanes'].items()})
