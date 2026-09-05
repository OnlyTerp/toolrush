"""ToolRush search v1 — in-process content search (scratch lab, NOT live tree).

Kills the VAL-S2 taxes:
  S1 `_has_command('rg')` = full _exec spawn+wrap per fresh task (~312ms).
     Prototype never probes: pure-Python re engine, no external binary.
  S2 `_search_with_rg` = full _exec spawn+wrap per call (~312ms).
     Prototype walks + matches in-process, zero spawns.
  S3 `_filter_read_blocked_search_results` = 262ms for 40 results (~7ms
     each: per-match _resolve_path_for_task + get_read_block_error).
     Prototype applies the REAL guard once per unique FILE (verdicts
     identical — the guard is path-level, not match-level), so N matches
     in one file cost one guard call.

Contract: returns list of (path, line_no, line) tuples. VAL-S4 compares
match SETS vs the harness path via comm, not envelopes.

Kill-switch (VAL-S5): TOOLRUSH_SEARCH=0 -> real registry.dispatch
(same precedent as wave-1 TOOLRUSH_FASTLANE=0).

Safety: local backend only. Respects the harness's own read-block guard
(the real function, not a reimplementation), plus redaction stays with
the caller. Binary files skipped via null-byte sniff (same rule as
toolrush.py fast_read).
"""
import fnmatch
import os
import re
import sys
from pathlib import Path

USE_FASTSEARCH = os.environ.get("TOOLRUSH_SEARCH", "1") == "1"

_HERMES = Path("C:/dev/AppData/Local/hermes/hermes-agent")
if str(_HERMES) not in sys.path:
    sys.path.insert(0, str(_HERMES))

_guard_fn = None
_VERDICTS = {}  # (normpath, task_id) -> bool. Guard verdicts are path-level
_VERDICTS_LOCK = None  # + task-deterministic: same path+task = same verdict.
import threading as _th

_VERDICTS_LOCK = _th.Lock()


def _guard():
    """The REAL harness read-block guard (same verdicts, called per file)."""
    global _guard_fn
    if _guard_fn is None:
        from tools.file_tools import _search_result_read_block_error

        _guard_fn = _search_result_read_block_error
    return _guard_fn


def guard_allowed(normpath, task_id="toolrush"):
    """Memoized REAL-guard verdict. First path: real call. Repeat: dict hit."""
    key = (normpath, task_id)
    with _VERDICTS_LOCK:
        v = _VERDICTS.get(key)
    if v is None:
        v = _guard()(normpath, task_id) is None
        with _VERDICTS_LOCK:
            _VERDICTS[key] = v
    return v


def fast_search(pattern, path, file_glob=None, limit=50, offset=0, task_id="toolrush"):
    """In-process regex content search. Returns [(path, line_no, line)]."""
    rx = re.compile(pattern)
    root = Path(path)
    if not root.is_absolute():
        root = Path(os.getcwd()) / root
    guard = _guard()
    blocked_files = {}  # path str -> bool (memoized guard verdicts)
    hits = []

    def allowed(fpath):
        key = str(fpath)
        v = blocked_files.get(key)
        if v is None:
            v = guard_allowed(key, task_id)
            blocked_files[key] = v
        return v

    names = sorted(os.listdir(root)) if root.is_dir() else []
    # deterministic walk order so pagination is stable
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if file_glob and not fnmatch.fnmatch(fn, file_glob):
                continue
            fp = Path(dirpath) / fn
            if fp.suffix.lower() in (
                ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
                ".pyc", ".pyo",
            ):
                continue
            try:
                raw = fp.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:8000]:
                continue
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                continue
            if not allowed(fp.resolve()):
                continue
            for no, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    hits.append((str(fp), no, line))
    return hits[offset : offset + limit]


def toolrush_search(pattern, path, file_glob=None, limit=50, offset=0, task_id="toolrush"):
    """Dispatch with kill-switch: SEARCH=0 -> real harness path."""
    if not USE_FASTSEARCH:
        from tools.registry import registry

        return registry.dispatch(
            "search_files",
            {
                "pattern": pattern,
                "target": "content",
                "path": path,
                "file_glob": file_glob,
                "output_mode": "content",
                "limit": limit,
                "offset": offset,
            },
            task_id=task_id,
        )
    return fast_search(pattern, path, file_glob, limit, offset, task_id)


if __name__ == "__main__":
    hits = toolrush_search("needle_alpha", "C:/dev/toolrush/benchsearch", limit=50)
    files = {h[0] for h in hits}
    print(f"selftest: {len(hits)} hits in {len(files)} files")
    assert len(files) == 40, f"expected 40 files, got {len(files)}"
    assert all(h[2].strip().startswith("second needle_alpha") for h in hits)
    print("SELFTEST-OK")
