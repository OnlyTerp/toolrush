"""Drift check: _is_readonly_terminal_command (helper layer) vs toolrush_admission.readonly.
The helper must never be MORE permissive than the base admission gate."""
import os, sys

sys.path.insert(0, r"C:/dev/AppData/Local/hermes/hermes-agent")
os.environ.setdefault("HERMES_HOME", os.path.join(__import__('tempfile').gettempdir(), "toolrush-reviewer-home"))

from agent.tool_dispatch_helpers import _is_readonly_terminal_command as ro_full
from agent.toolrush_admission import readonly as ro_base
import itertools, random, string

words = ["ls", "cat", "rm", "git", "curl", "echo", "rg", "sed", "find", "awk", "tee",
         ">", ">>", "<", "|", "&&", ";", "$(", "`", "x", "-rf", "/tmp/f", "status",
         "log", "push", "-o", "http://x.com", "-H", "$(cat t)", "python", "-c",
         "open", "w", ">", "sudo", "chmod", "env", "FOO=1", "--exec", "-delete",
         "&", "(", ")", "{", "}", "<<" , "2>", "$PATH", "${}", "\n", "\t"]
random.seed(42)
drift = []
for trial in range(4000):
    n = random.randint(1, 6)
    cmd = " ".join(random.choice(words) for _ in range(n))
    b = ro_base(cmd)
    f = ro_full(cmd)
    if f and not b:
        drift.append(cmd)
        if len(drift) >= 5:
            break
print(f"helper-more-permissive-than-base cases: {len(drift)}")
for c in drift:
    print("  DRIFT:", repr(c))
print("VERDICT:", "PASS" if not drift else "FAIL")
