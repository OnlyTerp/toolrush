"""Dissect T1: time each layer of ONE read_file dispatch, real code paths only.

Layers (outer -> inner):
 L0 registry.dispatch total
 L1 read path: normalize + device guard + resolve + special-file guard
 L2 extractable-document probe (is_extractable_document)
 L3 raw file read + line-number render
 L4 dedup/stub bookkeeping + tracker writes
 L5 redact_sensitive_text scan
 L6 registry normalize + tool_error/json envelope
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERMES = Path("C:/dev/AppData/Local/hermes/hermes-agent")
sys.path.insert(0, str(HERMES))

LAB = Path(__file__).resolve().parent
F = LAB / "benchfiles" / "mod_05.py"

from tools.registry import registry, discover_builtin_tools  # noqa: E402
discover_builtin_tools()
import tools.file_tools as ft  # noqa: E402,F401

NAMES = registry.get_all_tool_names()
assert "read_file" in NAMES
print(f"tools: {len(NAMES)}")

ARGS = {"path": str(F), "limit": 50}


def med(fn, reps=15):
    ts = sorted((lambda t0: (fn(), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter()) for _ in range(reps))
    return round(statistics.median(ts), 2)


out = {}

# L0: full dispatch, fresh tag each rep
c = [0]


def full():
    c[0] += 1
    return registry.dispatch("read_file", dict(ARGS), task_id=f"d0-{c[0]}")


r = full()
assert "module 5" in r, r[:150]
out["L0_full_dispatch_ms"] = med(full)

# L3 alone: raw read + add_line_numbers (the actual I/O + render)


def raw():
    text = F.read_text(encoding="utf-8")
    lines = text.splitlines()[:50]
    return "\n".join(f"{i+1}|{l}" for i, l in enumerate(lines))


out["L3_raw_read_render_ms"] = med(raw)

# L5 alone: redact_sensitive_text over the rendered page
page = raw()
try:
    from tools.file_tools import redact_sensitive_text

    def red():
        return redact_sensitive_text(page, file_read=True)

    out["L5_redact_scan_ms"] = med(red)
except Exception as e:
    out["L5_redact_scan_ms"] = f"ERR {e}"

# L2 alone: is_extractable_document probe
try:
    from tools.read_extract import is_extractable_document

    def probe():
        return is_extractable_document(str(F))

    out["L2_extract_probe_ms"] = med(probe)
except Exception as e:
    out["L2_extract_probe_ms"] = f"ERR {e}"

# L1 pieces: path resolution + stat guards
def resolve():
    return ft._resolve_path_for_task(str(F), "dz")


out["L1_path_resolve_ms"] = med(resolve)

# L6: json envelope cost — dumps+loads of a 4KB result


def env():
    s = json.dumps({"content": page}, ensure_ascii=False)
    return json.loads(s)["content"]


out["L6_json_envelope_ms"] = med(env)

# cProfile: one full dispatch, top cumulative offenders (proves, not guesses)
import cProfile  # noqa: E402
import io  # noqa: E402
import pstats  # noqa: E402

c[0] += 1
pr = cProfile.Profile()
pr.enable()
registry.dispatch("read_file", dict(ARGS), task_id=f"prof-{c[0]}")
pr.disable()
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(25)
prof = s.getvalue()
(LAB / "dissect_profile.txt").write_text(prof, encoding="utf-8")
# compact top-12 for the JSON
toplines = [l for l in prof.splitlines() if l.strip() and ("file_tools" in l or "registry" in l or "re." in l or "{built-in" in l)][:12]

out["profile_top"] = toplines
(LAB / "dissect_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
print("DISSECT-OK")
