"""Perf: fast lane vs rg lane on the WHOLE hermes-agent repo (~12k files).

Decision input for the walk budget: if the guard-on-page restructure wins
here too, the 500-file budget only guards pathological trees; keep it as
a safety valve."""
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERMES = Path(r"C:/dev/AppData/Local/hermes/hermes-agent")
sys.path.insert(0, str(HERMES))

from tools import file_tools as ft  # noqa: E402


def bench(label, pattern, path, runs=3, file_glob=None):
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
    bench("whole-repo", "def search", str(HERMES))
    bench("whole-repo-nomatch", "zzQQzz_no_such_token", str(HERMES))
