import os,sys
from pathlib import Path
sys.path.insert(0,'C:/dev/AppData/Local/hermes/hermes-agent')
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.toolrush_rg import native_context

e=LocalEnvironment(cwd='C:/dev/AppData/Local/hermes/hermes-agent'); o=ShellFileOperations(e)
def trace(frame,event,arg):
 if frame.f_code.co_name=='native_context' and event=='return': print('native_context return line',frame.f_lineno,'available',arg is not None)
 return trace
sys.settrace(trace)
for n in range(3):
 os.environ['TOOLRUSH_SEARCH']='0'
 print('shell',o.search('def ',path='tools/file_tools.py',limit=2).error)
 os.environ['TOOLRUSH_SEARCH']='1'
 x=native_context(o); print('native_available',x is not None)
 print('native',o.search('def ',path='tools/file_tools.py',limit=2).error)
sys.settrace(None); e.cleanup()
