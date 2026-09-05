"""VAL-S1: search baseline — REAL search_files dispatch over a fixed scratch tree."""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
from tools.registry import registry  # noqa: E402
import tools.file_tools  # noqa: E402,F401  (registers search_files)

names = registry.get_all_tool_names()
print(f"tools: {len(names)}")
assert "search_files" in names, "search_files not registered"

# Fixed scratch tree: 60 files, known match distribution (~40 files match)
tree = Path("C:/dev/toolrush/benchsearch")
tree.mkdir(exist_ok=True)
for i in range(60):
    tag = "needle_alpha" if i % 3 else "plain filler"
    (tree / f"f{i:03d}.txt").write_text(
        f"line one filler {i}\nsecond {tag} line {i}\nthird filler {i}\n",
        encoding="utf-8",
    )

args = {
    "pattern": "needle_alpha",
    "target": "content",
    "path": str(tree),
    "output_mode": "content",
    "limit": 50,
}
# Warm + verify once
r0 = json.loads(registry.dispatch("search_files", dict(args), task_id="s1-warm"))
assert "matches" in r0 or "results" in r0 or "total_count" in r0, f"shape? {str(r0)[:200]}"

N = 8
ts = []
for i in range(N):
    # distinct task_id per call defeats the consecutive-search guard AND the
    # read-tracker loop-blocker, so every call does real work
    a = dict(args, limit=50)
    t0 = time.perf_counter()
    r = registry.dispatch("search_files", a, task_id=f"s1-{i}")
    dt = (time.perf_counter() - t0) * 1000
    ts.append(dt)
ts.sort()
out = {
    "per_call_ms": [round(t, 1) for t in ts],
    "median": round(statistics.median(ts), 1),
    "p90": round(ts[int(len(ts) * 0.9)], 1),
}
print(json.dumps(out, indent=2))
open("C:/dev/toolrush/search_baseline.json", "w").write(json.dumps(out, indent=2))
print("SEARCH-BASELINE-OK")
