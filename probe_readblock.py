import sys
sys.path.insert(0, 'C:/dev/AppData/Local/hermes/hermes-agent')
from agent.file_safety import get_read_block_error
import inspect
print(inspect.signature(get_read_block_error))
for p in ['C:/trench-brain/trench/auth_public.py',
          'C:/trench-brain/trench/auth_public.py:pattern',
          '/api/today']:
    try:
        r = get_read_block_error(p)
        print(repr(p[:50]), '->', repr(r)[:200])
    except Exception as e:
        print(repr(p[:50]), 'ERR', e)
