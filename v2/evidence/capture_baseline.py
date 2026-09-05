"""Capture baseline without changing the live repo or hiding exit codes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path('C:/dev/AppData/Local/hermes/hermes-agent')
OUT = Path('C:/dev/.operator/toolrush-v2')
FILES = ['tools/file_operations.py', 'tools/file_tools.py', 'tools/toolrush_search.py',
         'agent/tool_dispatch_helpers.py', 'agent/tool_executor.py', 'run_agent.py',
         'tools/code_execution_tool.py', 'tests/tools/test_toolrush_search.py']
(OUT / 'baseline').mkdir(exist_ok=True)
manifest = {}
for rel in FILES:
    p = ROOT / rel
    if p.exists():
        data = p.read_bytes()
        target = OUT / 'baseline' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        manifest[rel] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
for command in [['git', 'status', '--porcelain=v1'], ['git', 'rev-parse', 'HEAD']]:
    r = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    manifest[' '.join(command)] = {'exit_code': r.returncode, 'output': r.stdout}
(OUT / 'inventory.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
patterns = ['test_file_operations*.py', 'test_file_ops*.py', 'test_file_tools*.py',
            'test_read_file_utf8*.py', 'test_read_special*.py', 'test_read_unicode*.py',
            'test_search*.py', 'test_toolrush_search.py', 'test_file_read_guards.py']
selected = sorted({str(p.relative_to(ROOT)).replace('\\', '/')
                   for pat in patterns for p in (ROOT/'tests/tools').glob(pat)})
(OUT/'baseline'/'test-selection.json').write_text(json.dumps(selected, indent=2))
cmd = [sys.executable, '-m', 'pytest', *selected, '-q', '--tb=short',
       '--junitxml='+str(OUT/'baseline'/'files.xml')]
start = time.perf_counter()
r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(OUT/'baseline'/'files.log').write_bytes(r.stdout)
record = {'command': cmd, 'exit_code': r.returncode, 'elapsed_s': time.perf_counter()-start}
(OUT/'baseline'/'files-run.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record, indent=2))
print(r.stdout.decode('utf-8', 'replace')[-18000:])
sys.exit(r.returncode)
