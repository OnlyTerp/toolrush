import sys
sys.path.insert(0, 'C:/dev/AppData/Local/hermes/hermes-agent')
from tools.approval import detect_hardline_command

DQ = chr(34)
pat = DQ + '/api/today' + DQ + '|' + DQ + '/api/grade' + DQ + '|' + DQ + '/api/now' + DQ + '|' + DQ + '/now' + DQ + '|handle_now|api_dispatch|API_HANDLERS'
print('PATTERN=', pat)
print('HARDLINE=', detect_hardline_command(pat))

# also test the full registry path for search_files if it has its own guard
import inspect
try:
    import tools.file_tools as ft
    src = inspect.getsource(ft)
    import re
    hits = [l.strip()[:100] for l in src.splitlines() if 'block' in l.lower() or 'approv' in l.lower() or 'danger' in l.lower()]
    print('FILE_TOOLS_GUARDS=', hits[:10])
except Exception as e:
    print('FILE_TOOLS_ERR=', e)
