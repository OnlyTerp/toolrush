"""Focused probe: does run_rg time out and reap when rg is slow? Deterministic:
rg -f patternfile over a huge synthetic tree with 1s timeout, or a slow reader."""
import os, subprocess, sys, tempfile, time

sys.path.insert(0, r"C:/dev/AppData/Local/hermes/hermes-agent")
from tools.toolrush_rg import run_rg

rg = subprocess.run(["where", "rg"], capture_output=True, text=True).stdout.splitlines()[0]
td = tempfile.mkdtemp(prefix="trslow")
# 3000 files x 2000 lines so a full scan takes >2s
os.makedirs(os.path.join(td, "tree"), exist_ok=True)
for i in range(3000):
    with open(os.path.join(td, "tree", f"f{i:05}.txt"), "w") as f:
        f.write(("filler line of text padding padding padding\n" * 2000))

ENVC = {**os.environ.copy(), "PATH": os.environ["PATH"]}
t0 = time.monotonic()
cap = run_rg([rg, "-n", "ZZZNOMATCH", "tree"], cwd=td, env=ENVC, max_lines=5, timeout=2)
dt = time.monotonic() - t0
print(f"reason={cap.reason} exit={cap.exit_code} bytes={len(cap.stdout)} dt={dt:.2f}")
print("VERDICT:", "PASS" if cap.reason == "search_timeout" and cap.exit_code == 124 and dt < 8 else "FAIL")
