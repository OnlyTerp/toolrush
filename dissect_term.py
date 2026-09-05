"""VAL-T2: dissect ONE real terminal echo — layer timings, profiled not guessed."""
import cProfile
import io
import json
import pstats
import sys
import time

sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
from tools.registry import registry, discover_builtin_tools  # noqa: E402

discover_builtin_tools()
import tools.terminal_tool as tt  # noqa: E402,F401

print(f"tools: {len(registry.get_all_tool_names())}", flush=True)

# Layer probes (real functions, single call each, warm process)
layers = {}


def probe(name, fn):
    t0 = time.perf_counter()
    fn()
    layers[name] = round((time.perf_counter() - t0) * 1000, 2)


probe("L1_get_env_config", lambda: tt._get_env_config())
probe(
    "L2_session_cwd",
    lambda: tt.get_session_cwd("t2-probe") or tt._get_env_config()["cwd"],
)
probe(
    "L3_resolve_command_cwd",
    lambda: tt._resolve_command_cwd(
        workdir=None, default_cwd=tt._get_env_config()["cwd"]
    ),
)

# L0 full dispatch + cProfile naming the tax
pr = cProfile.Profile()
pr.enable()
t0 = time.perf_counter()
r = registry.dispatch("terminal", {"command": "echo termbench"}, task_id="t2-full")
l0 = (time.perf_counter() - t0) * 1000
pr.disable()
assert "termbench" in r, f"echo wrong: {r[:150]}"
layers["L0_full_dispatch"] = round(l0, 2)

s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(30)
prof = s.getvalue()
open("C:/dev/wirebench/toolrush/dissect_term_profile.txt", "w").write(prof)

# Top cumulative lines for the report
top = [l for l in prof.splitlines() if "terminal_tool.py" in l or "base.py" in l or "deadline.py" in l or "local.py" in l][:15]
out = {"layers_ms": layers, "profile_top": top}
print(json.dumps(out, indent=2))
open("C:/dev/wirebench/toolrush/dissect_term.json", "w").write(json.dumps(out, indent=2))
print("DISSECT-TERM-OK")
