"""VAL-D1/D2: registry-layer tax — trivial handler, direct vs REAL dispatch."""
import cProfile
import io
import json
import pstats
import statistics
import sys
import time

sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
from tools.registry import registry  # noqa: E402

FIXED = "toolrush-noop-ok"


def _noop(args, **kw):
    return FIXED


from tools.registry import ToolEntry  # noqa: E402

registry._tools["toolrush_noop"] = ToolEntry(
    name="toolrush_noop",
    toolset="toolrush",
    schema={"name": "toolrush_noop", "description": "noop", "parameters": {}},
    handler=_noop,
    check_fn=None,
    requires_env=None,
    is_async=False,
    description="noop",
    emoji="⚡",
)
print(f"tools: {len(registry.get_all_tool_names())}", flush=True)
assert registry.dispatch("toolrush_noop", {}, task_id="d1-warm") == FIXED

N = 25


def med(fn):
    ts = sorted(
        (lambda t0: (fn(), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter())
        for _ in range(N)
    )
    return round(statistics.median(ts), 3), round(ts[int(len(ts) * 0.9)], 3)


direct_m, direct_p90 = med(lambda: _noop({}, task_id="d1-x"))
disp_m, disp_p90 = med(lambda: registry.dispatch("toolrush_noop", {}, task_id="d1-x"))
print(json.dumps({
    "direct_ms": {"median": direct_m, "p90": direct_p90},
    "dispatch_ms": {"median": disp_m, "p90": disp_p90},
    "registry_tax_ms": round(disp_m - direct_m, 3),
}, indent=2))

pr = cProfile.Profile()
pr.enable()
registry.dispatch("toolrush_noop", {}, task_id="d1-prof")
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(20)
prof = s.getvalue()
open("C:/dev/toolrush/dissect_dispatch_profile.txt", "w").write(prof)
top = [l for l in prof.splitlines() if "registry.py" in l or "model_tools" in l][:12]
print(json.dumps({"profile_top": top}, indent=2))
print("DISPATCH-D1D2-OK")
