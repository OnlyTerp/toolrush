"""VAL-S2: dissect ONE real search_files call — layer timings, profiled not guessed."""
import cProfile
import io
import json
import pstats
import sys
import time

sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
from tools.registry import registry  # noqa: E402
import tools.file_tools as ft  # noqa: E402

print(f"tools: {len(registry.get_all_tool_names())}", flush=True)
args = {
    "pattern": "needle_alpha",
    "target": "content",
    "path": "C:/dev/toolrush/benchsearch",
    "output_mode": "content",
    "limit": 50,
}

layers = {}


def probe(name, fn):
    t0 = time.perf_counter()
    fn()
    layers[name] = round((time.perf_counter() - t0) * 1000, 2)


probe(
    "L1_search_tool_direct",
    lambda: ft.search_tool(
        pattern="needle_alpha",
        target="content",
        path="C:/dev/toolrush/benchsearch",
        output_mode="content",
        limit=50,
        task_id="s2-direct",
    ),
)

pr = cProfile.Profile()
pr.enable()
t0 = time.perf_counter()
r = registry.dispatch("search_files", dict(args), task_id="s2-full")
l0 = (time.perf_counter() - t0) * 1000
pr.disable()
assert "needle_alpha" in r, f"no matches? {r[:200]}"
layers["L0_full_dispatch"] = round(l0, 2)

s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(35)
prof = s.getvalue()
open("C:/dev/toolrush/dissect_search_profile.txt", "w").write(prof)

top = [
    l
    for l in prof.splitlines()
    if "file_tools.py" in l
    or "file_operations.py" in l
    or "base.py" in l
    or "deadline.py" in l
    or "local.py" in l
][:18]
out = {"layers_ms": layers, "profile_top": top}
print(json.dumps(out, indent=2))
open("C:/dev/toolrush/dissect_search.json", "w").write(json.dumps(out, indent=2))
print("DISSECT-SEARCH-OK")
