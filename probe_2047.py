import sys
sys.path.insert(0, 'C:/dev/AppData/Local/hermes/hermes-agent')
from tools.approval import (
    detect_hardline_command,
    _normalize_command_for_detection,
    _quoted_grep_pattern_spans,
)

BS = chr(92)   # backslash
DQ = chr(34)   # double quote
SQ = chr(39)   # single quote
# Verbatim from agent.log:116251 — pattern ends ( ... [^<BS><DQ>]* with CLOSING quote
cmd = ('cd C:/trench-brain && sed -n ' + SQ + '7652,7800p' + SQ
       + ' trench/auth_public.py | grep -n -o -E ' + DQ
       + 'add_(get|post)' + BS + '(' + DQ + '[^)]*' + DQ + ' | head -100')
print('CMD=', cmd)
norm = _normalize_command_for_detection(cmd)
print('NORM=', repr(norm))
print('SPANS=', _quoted_grep_pattern_spans(norm))
print('VERDICT=', detect_hardline_command(cmd))
