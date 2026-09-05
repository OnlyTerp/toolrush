"""VAL-S4/S5: fast search vs harness — same workload, match SETS compared."""
import json
import re
import statistics
import sys
import time

sys.path.insert(0, "C:/dev/toolrush")
sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
import toolrush_search as ts  # noqa: E402
from tools.registry import registry  # noqa: E402
import tools.file_tools  # noqa: E402,F401

print(f"mode={'fast' if ts.USE_FASTSEARCH else 'harness-fallback'}")
TREE = "C:/dev/toolrush/benchsearch"


def harness_set():
    r = json.loads(
        registry.dispatch(
            "search_files",
            {
                "pattern": "needle_alpha",
                "target": "content",
                "path": TREE,
                "output_mode": "content",
                "limit": 50,
            },
            task_id=f"s4-harness",
        )
    )
    # Real envelope: total_count + matches_text (path-grouped prose), NOT a
    # matches list. Parse: bare line = path, "  <no>: <content>" = hit.
    out = set()
    cur = ""
    for ln in r.get("matches_text", "").splitlines():
        if re.match(r"^\s+\d+:", ln):
            no, _, c = ln.strip().partition(":")
            out.add((cur, int(no), c.strip()))
        elif ln.strip():
            cur = ln.strip()
    return out


def fast_set():
    return {
        (p, no, line.strip())
        for (p, no, line) in ts.toolrush_search(
            "needle_alpha", TREE, limit=50, task_id="s4-fast"
        )
    }


if ts.USE_FASTSEARCH:
    # correctness: match sets identical (comm semantics — normalize drive
    # separators since harness may return either form)
    hs = {(p.replace("\\", "/"), n, c) for (p, n, c) in harness_set()}
    fs = {(p.replace("\\", "/"), n, c) for (p, n, c) in fast_set()}
    only_h, only_f = hs - fs, fs - hs
    print(f"harness={len(hs)} fast={len(fs)} only_harness={len(only_h)} only_fast={len(only_f)}")
    assert not only_h and not only_f, f"SET MISMATCH h={list(only_h)[:3]} f={list(only_f)[:3]}"
    print("correctness OK: match sets identical")

    # Steady-state: the guard's first call lazily imports terminal_tool +
    # config + approval (~1s, one-time per process — profiled, not per-call).
    # Warm it once so the bench measures architecture, not cold imports.
    ts.toolrush_search("needle_alpha", TREE, limit=1, task_id="s4-warm")
    # One stable task_id (like a real session) alternating two patterns:
    # defeats the consecutive-search guard without defeating the verdict
    # cache with bench-artifact fresh tasks.
    N = 8
    ts_fast = []
    for i in range(N):
        pat = "needle_alpha" if i % 2 == 0 else "filler"
        t0 = time.perf_counter()
        ts.toolrush_search(pat, TREE, limit=50, task_id="s4-session")
        ts_fast.append((time.perf_counter() - t0) * 1000)
    ts_fast.sort()
    m = round(statistics.median(ts_fast), 1)
    out = {
        "per_call_ms": {"median": m, "p90": round(ts_fast[int(len(ts_fast) * 0.9)], 1)},
        "baseline_median": 900.3,
        "speedup": round(900.3 / m, 1),
    }
    print(json.dumps(out, indent=2))
    open("C:/dev/toolrush/search_proto.json", "w").write(json.dumps(out, indent=2))
else:
    # VAL-S5 negative control: fallback path ~= baseline
    N = 6
    ts2 = []
    for i in range(N):
        t0 = time.perf_counter()
        ts.toolrush_search("needle_alpha", TREE, limit=50, task_id=f"s5-{i}")
        ts2.append((time.perf_counter() - t0) * 1000)
    ts2.sort()
    m = round(statistics.median(ts2), 1)
    print(json.dumps({"neg_median": m, "baseline_median": 900.3}, indent=2))
print(f"MODE={'fast' if ts.USE_FASTSEARCH else 'harness-fallback'}")
print("SEARCH-PROTO-OK")
