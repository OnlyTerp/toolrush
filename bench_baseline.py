"""VAL-BASE-01/02: baseline tool-call latency bench — REAL registry.dispatch + REAL handlers, no mocks.

Harness honesty notes (learned from two failed runs):
- read_file has a per-task dedup cache: 2nd identical (path,offset,limit) read
  returns a stub, 3rd+ hard-BLOCKs. So every timed rep uses a FRESH task_id
  (tag) -> each call pays full dispatch+read, like a real agent turn.
- A separate T1b workload measures the stub path itself (that IS a real
  optimization already in the harness — quantify it, don't ignore it).
"""
import concurrent.futures
import json
import statistics
import sys
import time
from pathlib import Path

HERMES = Path("C:/dev/AppData/Local/hermes/hermes-agent")
sys.path.insert(0, str(HERMES))

LAB = Path(__file__).resolve().parent
FILES = LAB / "benchfiles"
N_FILES = 20

FILES.mkdir(exist_ok=True)
for i in range(N_FILES):
    p = FILES / f"mod_{i:02d}.py"
    if not p.exists():
        lines = [f"# module {i}"] + [f"def func_{i}_{j}(x):\n    return x * {j} + {i}" for j in range(60)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

from tools.registry import registry, discover_builtin_tools  # noqa: E402
discover_builtin_tools()
import tools.file_tools  # noqa: E402,F401
import tools.terminal_tool  # noqa: E402,F401

NAMES = registry.get_all_tool_names()
for need in ("read_file", "search_files", "terminal"):
    assert need in NAMES, f"{need} not registered"
print(f"registered tools: {len(NAMES)}")


def read_one(i, tag):
    return registry.dispatch(
        "read_file", {"path": str(FILES / f"mod_{i:02d}.py"), "limit": 50}, task_id=f"tag-{tag}-{i}"
    )


def timeit(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return round(statistics.median(ts), 2), round(ts[int(len(ts) * 0.9)], 2)


out = {}

# warmup
r = read_one(0, "warm")
assert "module 0" in r, f"read_file content wrong: {r[:150]}"

# T1: single read dispatch tax, full cost every rep (unique tag per rep)
_ctr = [0]


def read_fresh():
    _ctr[0] += 1
    return read_one(_ctr[0] % N_FILES, f"t1-{_ctr[0]}")


med, p90 = timeit(read_fresh, 50)
out["T1_single_read_dispatch_ms"] = {"median": med, "p90": p90}

# T1b: stub path — same task, same file, 2nd read returns dedup stub
r1 = registry.dispatch("read_file", {"path": str(FILES / "mod_01.py"), "limit": 50}, task_id="stub-probe")
assert "module 1" in r1


def read_stub():
    return registry.dispatch("read_file", {"path": str(FILES / "mod_01.py"), "limit": 50}, task_id="stub-probe")


# only ONE stub read is legal per key (2nd stub blocks), so time single calls across fresh keys
def stub_once(k):
    registry.dispatch("read_file", {"path": str(FILES / f"mod_{k % N_FILES:02d}.py"), "limit": 50}, task_id=f"stub-{k}")
    t0 = time.perf_counter()
    registry.dispatch("read_file", {"path": str(FILES / f"mod_{k % N_FILES:02d}.py"), "limit": 50}, task_id=f"stub-{k}")
    return (time.perf_counter() - t0) * 1000


sts = sorted(stub_once(k) for k in range(20))
out["T1b_dedup_stub_ms"] = {"median": round(statistics.median(sts), 2), "p90": round(sts[18], 2)}

# T2: sequential 20x distinct-file reads, fresh tag so all pay full cost
def seq_batch(k):
    for i in range(N_FILES):
        rr = read_one(i, f"seq-{k}")
        assert "module" in rr, f"seq content wrong: {rr[:100]}"


seq_batch("w")
t0 = time.perf_counter()
for k in range(3):
    seq_batch(k)
out["T2_seq_20x_read_ms"] = {"per_batch_avg": round((time.perf_counter() - t0) * 1000 / 3, 1)}

# T3: concurrent 20x on a FRESH pool per batch (mirrors today's executor)
def conc_batch_fresh(k):
    def one(i):
        rr = read_one(i, f"cf-{k}")
        assert "module" in rr
        return rr

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=20)
    try:
        return list(ex.map(one, range(N_FILES)))
    finally:
        ex.shutdown(wait=True)


conc_batch_fresh("w")
t0 = time.perf_counter()
for k in range(3):
    conc_batch_fresh(k)
out["T3_conc_20x_freshpool_ms"] = {"per_batch_avg": round((time.perf_counter() - t0) * 1000 / 3, 1)}

# T3b: same batch on a PERSISTENT pool
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=20)


def conc_batch_persist(k):
    def one(i):
        rr = read_one(i, f"cp-{k}")
        assert "module" in rr
        return rr

    return list(POOL.map(one, range(N_FILES)))


conc_batch_persist("w")
t0 = time.perf_counter()
for k in range(3):
    conc_batch_persist(k)
out["T3b_conc_20x_persistpool_ms"] = {"per_batch_avg": round((time.perf_counter() - t0) * 1000 / 3, 1)}

# T4: search_files x5, distinct patterns (all match real code)
def do_search(k):
    return registry.dispatch(
        "search_files",
        {"pattern": f"def func_{k}_", "path": str(FILES), "file_glob": "*.py", "output_mode": "files_only"},
        task_id=f"srch-{k}",
    )


s = do_search(1)
assert "mod_" in s, f"search content wrong: {s[:200]}"
t0 = time.perf_counter()
for k in range(1, 6):
    do_search(k)
out["T4_5x_search_ms"] = {"per_call_avg": round((time.perf_counter() - t0) * 1000 / 5, 1)}

# T5: terminal echo x10, distinct payloads
def do_term(k):
    return registry.dispatch("terminal", {"command": f"echo hello-bench-{k}"}, task_id=f"term-{k}")


te = do_term("w")
assert "hello-bench" in te, f"terminal content wrong: {te[:200]}"
t0 = time.perf_counter()
for k in range(10):
    do_term(k)
out["T5_10x_terminal_echo_ms"] = {"per_call_avg": round((time.perf_counter() - t0) * 1000 / 10, 1)}

(LAB / "baseline_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
print("BASELINE-BENCH-OK")
