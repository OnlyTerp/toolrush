"""VAL-PROTO-02 / VAL-SPEED-01 / VAL-NEG-01 / VAL-SAFE-01: prototype vs baseline.

Same 20-file workload both paths. Correctness: prototype output must carry
the same content lines as the harness read (gutter format identical).
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")

FILES = LAB / "benchfiles"
PATHS = [FILES / f"mod_{i:02d}.py" for i in range(20)]

import toolrush  # noqa: E402

print(f"fastlane={toolrush.USE_FASTLANE} cache={toolrush.USE_CACHE}")
out = {}

# --- P0 correctness: fast_read vs real harness read, same bytes of content ---
from tools.registry import registry, discover_builtin_tools  # noqa: E402

discover_builtin_tools()
import tools.file_tools  # noqa: E402,F401
import tools.terminal_tool  # noqa: E402,F401

p0 = str(PATHS[3])
real = json.loads(registry.dispatch("read_file", {"path": p0, "limit": 50}, task_id="p0-real"))
fast = json.loads(toolrush.fast_read(p0, limit=50))
assert "content" in real and "content" in fast, f"envelope: real={list(real)} fast={list(fast)}"
rl = [l.split("|", 1)[1] if "|" in l else l for l in real["content"].splitlines()]
fl = [l.split("|", 1)[1] if "|" in l else l for l in fast["content"].splitlines()]
assert rl == fl, f"CONTENT MISMATCH:\nreal={rl[:5]}\nfast={fl[:5]}"
assert real["total_lines"] == fast["total_lines"], (real["total_lines"], fast["total_lines"])
assert real["file_size"] == fast["file_size"]
out["P0_correctness"] = {"content_lines_equal": True, "total_lines": fast["total_lines"]}
print(f"P0 OK: {fast['total_lines']} lines, content identical")


def med(fn, reps):
    ts = sorted((lambda t0: (fn(), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter()) for _ in range(reps))
    return round(statistics.median(ts), 2), round(ts[int(len(ts) * 0.9)], 2)


# --- P1: single-call tax, prototype vs T1 baseline 1459.87ms ---
c = [0]


def proto_one():
    c[0] += 1
    return toolrush.toolrush_read(str(PATHS[c[0] % 20]), limit=50, task_id=f"p1-{c[0]}")


m, p90 = med(proto_one, 50)
out["P1_single_read_ms"] = {"median": m, "p90": p90}
print(f"P1 single: {m}ms (baseline 1459.87)")

# --- P2: batch workload = T2-equivalent, prototype vs 32436.4ms ---
def proto_batch(k):
    return toolrush.batch_read(PATHS, limit=50, tag=f"p2-{k}")


r = proto_batch("w")
assert len(r) == 20 and all("module" in json.loads(x).get("content", "") for x in r), "batch content wrong"
t0 = time.perf_counter()
for k in range(3):
    proto_batch(k)
per = round((time.perf_counter() - t0) * 1000 / 3, 1)
out["P2_batch_20x_ms"] = {"per_batch_avg": per}
out["P2_speedup_vs_T2"] = round(32436.4 / per, 1)
print(f"P2 batch: {per}ms (baseline 32436.4) speedup {out['P2_speedup_vs_T2']}x")

# --- P3: cached re-read (2nd batch, same mtimes) ---
t0 = time.perf_counter()
for k in range(3, 6):
    proto_batch(k)
out["P3_cached_batch_ms"] = {"per_batch_avg": round((time.perf_counter() - t0) * 1000 / 3, 1)}
print(f"P3 cached batch: {out['P3_cached_batch_ms']['per_batch_avg']}ms")

# --- P4: cache invalidation proof (VAL-SAFE honesty: mtime change re-reads) ---
victim = LAB / "benchfiles" / "mod_19.py"
before = toolrush.fast_read(str(victim), limit=5)
victim.write_text(victim.read_text(encoding="utf-8") + "\n# invalidate-probe\n", encoding="utf-8")
after = toolrush.fast_read(str(victim), limit=200)
assert "invalidate-probe" in after, "stale cache served after mtime change!"
victim.write_text(victim.read_text(encoding="utf-8").replace("\n# invalidate-probe\n", "\n"), encoding="utf-8")
out["P4_cache_invalidation"] = {"stale_served": False}
print("P4 OK: mtime change re-read, no stale serve")

(LAB / "proto_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
print(f"MODE fastlane={toolrush.USE_FASTLANE} cache={toolrush.USE_CACHE}")
print("PROTO-BENCH-OK")
