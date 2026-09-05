import sys
sys.path.insert(0, 'C:/dev/AppData/Local/hermes/hermes-agent')
from tools.approval import detect_hardline_command

DQ = chr(34)
SQ = chr(39)
# Verbatim shape of the model's new command: grep -E with "" and '' and ) all
# inside the double-quoted pattern.
cmd = ('cd C:/trench-brain && grep -rn -l -E ' + DQ + '/api/now|/api/wallets|now.html' + DQ
       + ' trench/.py | head; echo ===; grep -rn -E ' + DQ + DQ + '/now' + DQ + '|'
       + SQ + '/now' + SQ + '|' + DQ + '/' + DQ + ')'
       + DQ + ' trench/main.py trench/app.py 2>/dev/null | head -20')
print('CMD=', cmd)
print('VERDICT=', detect_hardline_command(cmd))
