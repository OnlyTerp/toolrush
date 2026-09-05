import importlib.util,importlib,json,sys
from pathlib import Path
P=Path('C:/dev/AppData/Local/hermes/plugins/toolrush');sys.path.insert(0,str(P.parent.parent/'hermes-agent'))
s=importlib.util.spec_from_file_location('cmpc',P/'compat.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
payload=json.loads((P/'payload.json').read_text());row=payload['lanes']['files'][0];mod=importlib.import_module(row['module']);old=mod
for t in row['qualname'].split('.'):old=getattr(old,t)
new=m.compile_function(row['after'],mod,row['qualname'].split('.')[-1])
a,b=m.fingerprint(old.__code__),m.fingerprint(new.__code__)
for i,(x,y) in enumerate(zip(a,b)):
 if x!=y:print(i,str(x)[:1400],str(y)[:1400])
print('filenames',old.__code__.co_filename,new.__code__.co_filename)
