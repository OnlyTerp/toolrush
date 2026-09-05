"""Perf: fast lane vs rg lane, end-to-end through search_tool.

Small tree (fast lane's home turf) + whole-repo (rg's home turf).
Unique task_id per call keeps the consecutive-search guard out of the way.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERMES = Path(r"C:/dev/AppData/Local/hermes/hermes-agent")
sys.path.insert(0, str(HERMES))

from tools import file_tools as ft  # noqa: E402


def bench(label, pattern, path, runs=5, file_glob=None):
    fast_t, slow_t, fast_rows, slow_rows = [], [], [], []
    for i in range(runs):
        os.environ["TOOLRUSH_SEARCH"] = "1"
        t0 = time.perf_counter()
        out = ft.search_tool(pattern=pattern, target="content", path=path,
                             file_glob=file_glob, limit=50, offset=0,
                             output_mode="content", context=0,
                             task_id=f"bench-fast-{label}-{i}")
        fast_t.append((time.perf_counter() - t0) * 1000)
        fast_rows.append(json.loads(out).get("total_count"))

        os.environ["TOOLRUSH_SEARCH"] = "0"
        t0 = time.perf_counter()
        out = ft.search_tool(pattern=pattern, target="content", path=path,
                             file_glob=file_glob, limit=50, offset=0,
                             output_mode="content", context=0,
                             task_id=f"bench-slow-{label}-{i}")
        slow_t.append((time.perf_counter() - t0) * 1000)
        slow_rows.append(json.loads(out).get("total_count"))
    os.environ["TOOLRUSH_SEARCH"] = "1"
    print(f"[{label}] pattern={pattern!r} file_glob={file_glob!r}")
    print(f"  FAST  median={statistics.median(fast_t):8.1f}ms  "
          f"min={min(fast_t):8.1f}ms  rows={fast_rows[0]}")
    print(f"  SLOW  median={statistics.median(slow_t):8.1f}ms  "
          f"min={min(slow_t):8.1f}ms  rows={slow_rows[0]}")
    print(f"  speedup={statistics.median(slow_t)/statistics.median(fast_t):6.1f}x  "
          f"rows-match={fast_rows == slow_rows}")


if __name__ == "__main__":
    tmp = Path(os.environ["TEMP"]) / "tr-perf-tree"
    tmp.mkdir(exist_ok=True)
    for i in range(20):
        d = tmp / f"mod{i:02d}"
        d.mkdir(exist_ok=True)
        for j in range(5):
            (d / f"f{j}.py").write_text(
                "\n".join(f"line {k} plain" for k in range(60))
                + f"\ndef handler_{i}_{j}(x): return x\n" * 3
            )
    bench("small-tree", "def handler_", str(tmp))

    bench("repo-tools", "_search_result_read_block_error", str(HERMES / "tools"))
    bench("repo-glob", "def search", str(HERMES / "tools"), file_glob="*.py")
