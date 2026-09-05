"""VAL-T3/T4: persistent shell vs harness terminal — same echo workload, both modes."""
import json
import statistics
import sys
import time

sys.path.insert(0, "C:/dev/wirebench/toolrush")
sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
import toolrush_exec as te  # noqa: E402
from tools.registry import registry, discover_builtin_tools  # noqa: E402

discover_builtin_tools()
import tools.terminal_tool  # noqa: E402,F401

print(f"mode={'persist' if te.USE_PERSIST else 'spawn'}")
N = 10


def med(fn):
    ts = sorted((lambda t0: (fn(), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter()) for _ in range(N))
    p90 = ts[int(len(ts) * 0.9)]
    return round(statistics.median(ts), 1), round(p90, 1)


# correctness: byte-identical stdout vs harness
harness_raw = registry.dispatch("terminal", {"command": "echo termbench"}, task_id="t3-harness")
harness_out = json.loads(harness_raw)["output"].strip()
proto_out, proto_rc = te.toolrush_exec("echo termbench")
assert proto_out.strip() == harness_out == "termbench", f"{proto_out!r} vs {harness_out!r}"
assert proto_rc == 0
o2, c2 = te.toolrush_exec("echo alpha && echo beta")
assert o2.strip().splitlines() == ["alpha", "beta"] and c2 == 0, f"{o2!r}"
print("correctness OK: byte-identical stdout, compound + rc clean")

m, p90 = med(lambda: te.toolrush_exec("echo termbench"))
out = {"per_call_ms": {"median": m, "p90": p90}, "baseline_median": 285.0, "speedup": round(285.0 / m, 1)}
print(json.dumps(out, indent=2))
open("C:/dev/wirebench/toolrush/term_proto.json", "w").write(json.dumps(out, indent=2))
print(f"MODE={'persist' if te.USE_PERSIST else 'spawn'}")
print("TERM-PROTO-OK")
