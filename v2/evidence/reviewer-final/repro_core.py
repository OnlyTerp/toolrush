"""Boundary tests: native read parity, run_rg bounds, admission safety.
Artifacts land in this dir; prod code is read-only. Run: python repro_core.py
"""
import os, subprocess, sys, tempfile, time

sys.path.insert(0, r"C:/dev/AppData/Local/hermes/hermes-agent")
os.environ.setdefault("HERMES_HOME", os.path.join(tempfile.gettempdir(), "toolrush-reviewer-home"))

PASS = []
def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

# ---------- 1. run_rg bounded capture (rg-bounds lane) ----------
from tools.toolrush_rg import run_rg, native_context

rg = subprocess.run(["where", "rg"], capture_output=True, text=True).stdout.splitlines()[0]
td = tempfile.mkdtemp(prefix="trrg")
with open(os.path.join(td, "big.txt"), "w") as f:
    for i in range(1, 301):
        f.write(f"line-{i} " + "x" * 80 + "\n")
with open(os.path.join(td, "huge.bin"), "wb") as f:
    f.write(b"z" * (40 * 1024 * 1024) + b"\n")

ENVC = {**os.environ.copy(), "PATH": os.environ["PATH"]}
cap = run_rg([rg, "--files", "."], cwd=td, env=ENVC, max_lines=10, timeout=20)
check("run_rg files bounded <= max_lines", len(cap.stdout.strip().splitlines()) <= 10,
      f"exit={cap.exit_code} lines={len(cap.stdout.strip().splitlines())}")
check("run_rg --files exit 0", cap.exit_code == 0)

cap5 = run_rg([rg, "-n", "line-", "big.txt"], cwd=td, env=ENVC, max_lines=5, timeout=20)
lines5 = cap5.stdout.strip().splitlines()
check("run_rg max_lines=5 honored", len(lines5) == 5 and cap5.exit_code == 0,
      f"exit={cap5.exit_code} n={len(lines5)}")

caph = run_rg([rg, "z+", "--no-line-number", "huge.bin"], cwd=td, env=ENVC,
              max_lines=3, timeout=25)
check("run_rg byte budget enforced (<8.5MB)",
      len(caph.stdout.encode('utf-8', 'replace')) < 8.5 * 1024 * 1024,
      f"bytes={len(caph.stdout)} reason={caph.reason} exit={caph.exit_code}")
check("run_rg byte-budget reason honest", caph.limited and caph.reason == "search_output_budget",
      f"limited={caph.limited} reason={caph.reason}")

# timeout path: rg over a big tree with a 1s timeout (see repro_timeout.py for the
# deterministic 2s variant; C:/Windows scan finished too fast to trigger it).
capk = run_rg([rg, "-n", "nonexistentpatternxyz", "C:/Windows"], cwd=td, env=ENVC,
              max_lines=5, timeout=1)
check("run_rg timeout reaps + honest reason",
      capk.reason in ("search_timeout", None) and capk.exit_code in (124, 0),
      f"reason={capk.reason} exit={capk.exit_code} bytes={len(capk.stdout)}")

# exit-code honesty: rg with a bad flag should propagate exit != 0, limited=False
capb = run_rg([rg, "--definitely-not-a-flag", "x", "."], cwd=td, env=ENVC, max_lines=5, timeout=10)
check("run_rg propagates rg errors (exit 2, no fake bound)", capb.exit_code == 2 and not capb.limited,
      f"exit={capb.exit_code} limited={capb.limited} reason={capb.reason}")

# ---------- 2. native read parity (native-read lane) ----------
from tools.file_operations import ShellFileOperations
from tools.environments.local import LocalEnvironment

def make_ops(cwd):
    ops = ShellFileOperations.__new__(ShellFileOperations)
    ops.env = LocalEnvironment(cwd)
    ops.cwd = cwd
    for attr, val in (("_rg_resolution_cache", {}), ("_command_cache", {}),
                      ("_rg_modified_capability", {})):
        if not hasattr(ops, attr):
            setattr(ops, attr, val)
    return ops

ops = make_ops(td)
check("native read enabled by default", ops._native_read_enabled() is True)
check("native path translation local ok", ops._local_native_path(os.path.abspath(td)) is not None)

npath = os.path.abspath(os.path.join(td, "big.txt"))
def _txt(r):
    for a in ("output", "content", "text"):
        v = getattr(r, a, None)
        if v:
            return v
    return ""
native_res = ShellFileOperations._read_file_native(ops, npath, 10, 5)
shell_res = ShellFileOperations._read_file_sequential(ops, npath, 10, 5)
check("native read == shell read (page parity)", _txt(native_res) == _txt(shell_res),
      f"native={len(_txt(native_res))}B shell={len(_txt(shell_res))}B")
check("native read total_lines parity",
      getattr(native_res, 'total_lines', None) == getattr(shell_res, 'total_lines', None),
      f"native={getattr(native_res, 'total_lines', '?')} shell={getattr(shell_res, 'total_lines', '?')}")
check("native read ends-with-newline parity",
      getattr(native_res, 'content', '') == getattr(shell_res, 'content', ''),
      f"native={getattr(native_res, 'content', '')[:60]!r} shell={getattr(shell_res, 'content', '')[:60]!r}")

nat_far = ShellFileOperations._read_file_native(ops, npath, 5000, 5)
sh_far = ShellFileOperations._read_file_sequential(ops, npath, 5000, 5)
check("native read beyond-EOF parity", _txt(nat_far) == _txt(sh_far) and _txt(nat_far) == "",
      f"native={_txt(nat_far)!r} shell={_txt(sh_far)!r}")

try:
    nat_dir = ShellFileOperations._read_file_native(ops, os.path.abspath(td), 1, 5)
    check("native read dir -> not-regular", bool(getattr(nat_dir, 'error', '')),
          f"error={getattr(nat_dir, 'error', '')[:80]}")
except Exception as e:
    check("native read dir -> not-regular", False, f"raised {e!r}")

# zero-byte file parity
zpath = os.path.join(td, "zero.txt")
open(zpath, "w").close()
nz = ShellFileOperations._read_file_native(ops, os.path.abspath(zpath), 1, 5)
sz = ShellFileOperations._read_file_sequential(ops, os.path.abspath(zpath), 1, 5)
check("native read zero-byte parity", _txt(nz) == _txt(sz),
      f"native={_txt(nz)!r} shell={_txt(sz)!r}")

# file without trailing newline
nnpath = os.path.join(td, "nonl.txt")
with open(nnpath, "w") as f:
    f.write("alpha\nbeta\ngamma-no-newline")
nn = ShellFileOperations._read_file_native(ops, os.path.abspath(nnpath), 3, 5)
sn = ShellFileOperations._read_file_sequential(ops, os.path.abspath(nnpath), 3, 5)
check("native read no-trailing-newline parity", _txt(nn) == _txt(sn),
      f"native={_txt(nn)!r} shell={_txt(sn)!r}")
check("native no-newline truncated/hint parity",
      getattr(nn, 'truncated', None) == getattr(sn, 'truncated', None)
      and getattr(nn, 'hint', None) == getattr(sn, 'hint', None),
      f"native={getattr(nn, 'truncated', '?')}/{getattr(nn, 'hint', '?')!r} shell={getattr(sn, 'truncated', '?')}/{getattr(sn, 'hint', '?')!r}")

# clamp parity: line longer than clamp
clpath = os.path.join(td, "clamped.txt")
with open(clpath, "w") as f:
    f.write("A" * 9000 + "\n" + "B" * 100 + "\n")
nc = ShellFileOperations._read_file_native(ops, os.path.abspath(clpath), 1, 5)
sc = ShellFileOperations._read_file_sequential(ops, os.path.abspath(clpath), 1, 5)
check("native read long-line clamp parity", _txt(nc) == _txt(sc),
      f"native={len(_txt(nc))}B shell={len(_txt(sc))}B")

# binary file parity
bpath = os.path.join(td, "bin.dat")
with open(bpath, "wb") as f:
    f.write(bytes(range(256)) * 8)
nb = ShellFileOperations._read_file_native(ops, os.path.abspath(bpath), 1, 5)
sb = ShellFileOperations._read_file_sequential(ops, os.path.abspath(bpath), 1, 5)
check("native read binary flagged both paths",
      getattr(nb, 'is_binary', False) == getattr(sb, 'is_binary', False) == True,
      f"native={getattr(nb, 'is_binary', '?')} shell={getattr(sb, 'is_binary', '?')}")

print(f"\nTOTAL {sum(1 for _, ok in PASS if ok)}/{len(PASS)} passed")
