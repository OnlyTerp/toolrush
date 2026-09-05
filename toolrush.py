"""ToolRush prototype v1 — fast local tool runtime (scratch lab, NOT the live tree).

Design (from results.md dissection):
  P1 local fast-lane read: one in-process open()/stat replaces up to 5 shell
     round-trips (stat probe + head|base64 sample + sed|cut page + wc -l count
     + tail -c1 newline probe). Same output contract: LINE_NUM|CONTENT gutter
     with max_line_length clamp, total_lines, file_size, truncated+hint,
     empty-file and beyond-EOF hints, BOM strip.
  P2 persistent pool: one process-wide DaemonThreadPoolExecutor for batches.
  P3 session file cache: (path,offset,limit)->(mtime, rendered) so repeat
     reads of unchanged files cost a dict lookup, not disk I/O. Mtime-keyed:
     a write changes mtime -> stale entries can never serve.

  Negative-control switches (VAL-NEG-01):
    TOOLRUSH_FASTLANE=0  -> bypass fast read, call real registry.dispatch
    TOOLRUSH_CACHE=0     -> bypass session cache (fast read still on)
"""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERMES = Path("C:/dev/AppData/Local/hermes/hermes-agent")
sys.path.insert(0, str(HERMES))

USE_FASTLANE = os.environ.get("TOOLRUSH_FASTLANE", "1") == "1"
USE_CACHE = os.environ.get("TOOLRUSH_CACHE", "1") == "1"

# Pool: persistent, daemon workers so a wedged read can never hold exit open
_POOL_LOCK = threading.Lock()
_POOL = None


def get_pool(max_workers=20):
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            from tools.daemon_pool import DaemonThreadPoolExecutor

            _POOL = DaemonThreadPoolExecutor(max_workers=max_workers)
        return _POOL


# Cache: {(path, offset, limit): (mtime_ns, rendered_str)}
_CACHE_LOCK = threading.Lock()
_CACHE = {}


def _max_line_length():
    try:
        from tools.tool_output_limits import get_max_line_length

        return get_max_line_length()
    except Exception:
        return 2000


def fast_read(path, offset=1, limit=50):
    """In-process local read. Same contract as read_file_tool's happy path."""
    from tools.file_operations import normalize_read_pagination

    offset, limit = normalize_read_pagination(offset, limit)
    p = Path(path)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    rp = p.resolve()
    if not rp.is_file():
        return json.dumps({"success": False, "error": f"File not found: {path}"}, ensure_ascii=False)
    if rp.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"):
        return json.dumps({"success": False, "error": "image — use vision"}, ensure_ascii=False)

    st = rp.stat()
    key = (str(rp), offset, limit)
    if USE_CACHE:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit is not None and hit[0] == st.st_mtime_ns:
            return hit[1]

    raw = rp.read_bytes()
    if b"\x00" in raw[:8000]:
        return json.dumps({"success": False, "error": "binary file"}, ensure_ascii=False)
    try:
        text = raw.decode("utf-8-sig")  # utf-8-sig strips BOM like _strip_bom
    except UnicodeDecodeError:
        return json.dumps({"success": False, "error": "binary file"}, ensure_ascii=False)

    lines = text.splitlines()
    total_lines = len(lines)
    file_size = st.st_size
    if file_size == 0:
        out = json.dumps(
            {"content": "", "total_lines": 0, "file_size": 0, "hint": "File is empty (0 bytes)."},
            ensure_ascii=False,
        )
        if USE_CACHE:
            with _CACHE_LOCK:
                _CACHE[key] = (st.st_mtime_ns, out)
        return out
    if offset > total_lines > 0:
        return json.dumps(
            {
                "content": "",
                "total_lines": total_lines,
                "file_size": file_size,
                "hint": f"Note: offset {offset} is beyond the end of the file "
                f"({total_lines} lines total). Retry with offset <= {total_lines}.",
            },
            ensure_ascii=False,
        )
    end_line = offset + limit - 1
    page = lines[offset - 1 : end_line]
    mll = _max_line_length()
    numbered = []
    for i, line in enumerate(page, start=offset):
        if len(line) > mll:
            line = line[:mll] + "... [truncated]"
        numbered.append(f"{i}|{line}")
    content = "\n".join(numbered)
    # Byte-parity with the harness path: its sed|cut page read always ends
    # with '\n', and its renderer splits that into a trailing phantom 'N|'
    # line (see its own 'cut always newline-terminates' comment). Reproduce
    # the quirk so outputs compare equal; flagged for removal upstream.
    content += f"\n{offset + len(page)}|"
    truncated = total_lines > end_line
    d = {
        "content": content,
        "total_lines": total_lines,
        "file_size": file_size,
        "truncated": truncated,
        "is_binary": False,
        "is_image": False,
    }
    if truncated:
        d["hint"] = (
            f"Use offset={end_line + 1} to continue reading "
            f"(showing {offset}-{end_line} of {total_lines} lines)"
        )
    out = json.dumps(d, ensure_ascii=False)
    if USE_CACHE:
        with _CACHE_LOCK:
            _CACHE[key] = (st.st_mtime_ns, out)
    return out


def toolrush_read(path, offset=1, limit=50, task_id="toolrush"):
    """Dispatch with kill-switches: FASTLANE=0 -> real harness path."""
    if not USE_FASTLANE:
        from tools.registry import registry

        return registry.dispatch("read_file", {"path": path, "offset": offset, "limit": limit}, task_id=task_id)
    return fast_read(path, offset, limit)


def batch_read(paths, limit=50, tag="batch"):
    """20-file batch over the persistent pool (P2). Order-preserving."""
    pool = get_pool(max_workers=20)

    def one(args):
        i, p = args
        return toolrush_read(str(p), limit=limit, task_id=f"{tag}-{i}")

    return list(pool.map(one, enumerate(paths)))


# Write lane (VAL-SAFE-01): per-path locks serialize overlapping writes.
# Reads take the same lock: never observe a torn write. Reads are ~1ms so
# exclusive (not shared) locking costs nothing measurable; correctness first.
_PATH_LOCKS_LOCK = threading.Lock()
_PATH_LOCKS = {}


def _lock_for(path_str):
    with _PATH_LOCKS_LOCK:
        lk = _PATH_LOCKS.get(path_str)
        if lk is None:
            lk = threading.Lock()
            _PATH_LOCKS[path_str] = lk
        return lk


def fast_write(path, text, mode="overwrite"):
    """In-process local write. Serialized per resolved path."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    rp = p.resolve()
    lk = _lock_for(str(rp))
    with lk:
        with open(rp, "a" if mode == "append" else "w", encoding="utf-8") as f:
            f.write(text)
        st = rp.stat()
    # Write changes mtime -> drop cached renders for this path, never stale.
    if USE_CACHE:
        with _CACHE_LOCK:
            for k in [k for k in _CACHE if k[0] == str(rp)]:
                del _CACHE[k]
    return json.dumps({"success": True, "path": str(rp), "file_size": st.st_size}, ensure_ascii=False)


def fast_read_locked(path, offset=1, limit=50):
    """Read holding the path lock: never observes a torn write."""
    p = Path(path)
    rp = (p if p.is_absolute() else Path(os.getcwd()) / p).resolve()
    with _lock_for(str(rp)):
        return fast_read(str(rp), offset, limit)
