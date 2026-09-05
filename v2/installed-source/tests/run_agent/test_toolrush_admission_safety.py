"""VAL-SAFE-05: explicit no-write terminal batch admission."""
import json
from types import SimpleNamespace
import pytest
from agent.tool_dispatch_helpers import _is_readonly_terminal_command as readonly, _plan_tool_batch_segments

UNSAFE = [
    'env python -c "open(\'file\',\'w\').write(\'x\')"',
    'wget https://example.invalid/download',
    'ssh-keygen -t ed25519 -f key',
    'cd other && ls',
    'git branch new-branch',
    'git config user.name changed',
    'git remote add new https://example.invalid',
    'git update-ref refs/heads/main deadbeef',
    'git -c alias.x=status x',
    'curl -o output https://example.invalid',
    'curl -X DELETE https://example.invalid',
    'curl --config config.txt',
    'curl -sO https://example.invalid/file',
    'sed "w output" input',
    'sed -n "e uname" input',
    'awk "BEGIN {system(\"cmd\")}"',
    'rg --pre malicious.py pattern .',
    'sort -o output input',
    'uniq input output',
    'xxd -r input output',
    'python malicious.py --version',
    'node -e "require(\"fs\").writeFileSync(\"x\",\"x\")" --version',
    'date -s 2020-01-01',
    'hostname newname',
    'echo ok 2> errors.txt',
    'printf -v STATE value',
    'FOO=value',
]

@pytest.mark.parametrize('command',UNSAFE)
def test_unsafe_commands_are_barriers(command):
    assert not readonly(command)
    def tc(name,args):
        return SimpleNamespace(id=name,type='function',function=SimpleNamespace(name=name,arguments=json.dumps(args)))
    segments=_plan_tool_batch_segments([tc('terminal',{'command':command}),tc('read_file',{'path':'a.txt'})])
    assert segments[0][0]=='sequential'

@pytest.mark.parametrize('command',[
    'git status --short','git log -5 --oneline','git diff --stat',
    'rg -n needle C:/repo','ls -la C:/repo',
    "sed -n '1,20p' file", 'python --version', 'node --version',
    'curl -s -m 5 http://127.0.0.1:18778/healthz',
    'grep -n needle $LOCALAPPDATA/config.txt',
])
def test_safe_read_commands_still_parallel(command):
    assert readonly(command)
