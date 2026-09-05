"""VAL-T1: terminal baseline — REAL harness terminal handler, echo workload."""
import json
import statistics
import sys
import time

sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
from tools.registry import registry, discover_builtin_tools  # noqa: E402

discover_builtin_tools()
import tools.terminal_tool  # noqa: E402,F401

names = registry.get_all_tool_names()
print(f"tools: {len(names)}")
assert "terminal" in names, "terminal tool not registered"

N = 10
ts = []
for i in range(N):
    t0 = time.perf_counter()
    r = registry.dispatch("terminal", {"command": "echo termbench"}, task_id=f"t1-{i}")
    dt = (time.perf_counter() - t0) * 1000
    ts.append(dt)
    assert "termbench" in r, f"echo content wrong: {r[:150]}"
ts.sort()
out = {
    "per_call_ms": [round(t, 1) for t in ts],
    "median": round(statistics.median(ts), 1),
    "p90": round(ts[int(len(ts) * 0.9)], 1),
}
print(json.dumps(out, indent=2))
open("C:/dev/wirebench/toolrush/term_baseline.json", "w").write(json.dumps(out, indent=2))
print("TERM-BASELINE-OK")
