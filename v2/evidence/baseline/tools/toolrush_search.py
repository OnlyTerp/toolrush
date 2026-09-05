"""ToolRush fast lane: in-process content search (live tree port).

Replaces the rg spawn + per-match guard walk for the common case with a
pure-Python streaming walk. Local backend only; every hard case fails OPEN
to the existing rg path (returns None -> caller falls back).

Pipeline parity with the rg lane (_search_with_rg -> search_tool):
  emit raw rows/files/counts -> window to fetch_limit (rg runs
  `| head -n fetch_limit`) -> read-block guard filter (per unique path,
  memoized — verdicts are path-level, so N matches in one file cost one
  guard call; this is the S3 tax killed) -> page slice [offset:offset+limit]
  -> redaction (per content string, file_read=True) -> envelope keys.

Envelope contract (mirrors SearchResult.to_dict(densify=True) + the
search_tool _omitted/_warning additions):
  total_count, matches_format+matches_text (>=5 page matches) or matches
  array (<5), files, counts, truncated, _omitted (same message string).

Known, documented deltas vs rg (behavior this engine does NOT replicate):
  - rg respects .gitignore/.ignore/.rgignore; this walk does not, so
    gitignored files MAY appear in fast-lane results (superset). Hidden
    files/dirs (dot-prefixed) ARE skipped, matching rg's default.
  - rg emits matches in its own traversal order; this walk is sorted and
    deterministic. Match SETS are compared separator-agnostically in tests
    (VAL-S4 law).
  - Non-UTF-8 bytes decode with errors='replace' (rg searches bytes).
  - rg's --max-columns 2000 preview cut is approximated by the 500-char
    content clamp the rg parser applies anyway.
  - truncated is always False in-window (rg sets it only on a search
    timeout; this lane has no external timeout to hit).

Fail-open cases (return None -> caller uses rg): missing/unreadable root,
context > 0, multiline patterns (regex \\n), output_mode outside
{content, files_only, count}, regex compile errors, walk OSError.

Kill-switch: env TOOLRUSH_SEARCH=0 or config toolrush.fast_search=false.
"""
import fnmatch
import io
import os
from pathlib import Path
from typing import Callable, Optional

_DENSIFY_MIN_MATCHES = 5  # file_operations.SearchResult._DENSIFY_MIN_MATCHES
_CONTENT_CLAMP = 500      # rg parser clamps content to 500 chars
_BINARY_SNIFF_BYTES = 8000
_MATCHES_FORMAT = (
    "path-grouped: each file path on its own line, followed by "
    "indented '<line>: <content>' rows for matches in that file"
)
_OMITTED_MSG = (
    "{} result(s) omitted because they target credential, "
    "token, cache, or secret-bearing environment files."
)
_SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".pyc", ".pyo",
)

# Walk budget (perf law 9/3): past these, the pure-Python walk loses to
# rg's Rust scanner (measured 0.7x on the hermes-agent repo) -> fail open.
_WALK_BUDGET_FILES = 500
_WALK_BUDGET_BYTES = 32 * 1024 * 1024


def _emit_path(root_input: str, root: Path, root_is_file: bool, fp: Path) -> str:
    """Path string exactly as the rg lane emits it. Empirically (rg 14,
    Windows, 9/3, two probes): rg echoes the root arg VERBATIM and joins
    with a BACKSLASH — `C:/x/tools\\file.py`, `.\\file.py`. Replicate that
    join, not os.path.join. Trailing separators in root_input are stripped
    (mild normalization; rg may differ there)."""
    if root_is_file:
        return root_input
    try:
        rel = fp.relative_to(root).as_posix()
    except ValueError:
        return str(fp)
    base = root_input.rstrip("/\\") or "."
    return f"{base}\\{rel.replace('/', chr(92))}"


def _iter_lines(fp: Path, scan_stats: Optional[dict] = None):
    """Yield (line_no, text) with the binary sniff + utf-8-sig decode.
    Accumulates bytes read into scan_stats["bytes"] for the walk budget."""
    with open(fp, "rb") as fh:
        head = fh.read(_BINARY_SNIFF_BYTES)
        if scan_stats is not None:
            scan_stats["bytes"] += len(head)
        if b"\x00" in head:
            return
        fh.seek(0)
        wrapper = io.TextIOWrapper(fh, encoding="utf-8-sig",
                                   errors="replace", newline="")
        for no, line in enumerate(wrapper, start=1):
            yield no, line.rstrip("\n")


def fast_search(
    pattern: str,
    root_input: str,
    resolved_root: str,
    file_glob: Optional[str],
    limit: int,
    offset: int,
    output_mode: str,
    task_id: str,
    guard_fn: Callable[[str, str], Optional[str]],
    redact_fn: Callable[[str], str],
    regex_module=None,
) -> Optional[dict]:
    """Run the in-process search and return the result envelope dict.

    ``guard_fn(path, task_id)`` must be the real read-block guard (returns
    error string or None); ``redact_fn(content)`` must be the real text
    redactor. Returns None for every case this lane does not prove
    equivalent to the rg lane.
    """
    import re as _re

    if regex_module is None:
        regex_module = _re

    if output_mode not in ("content", "files_only", "count"):
        return None
    # multiline (\n) patterns: the rg lane enables multiline mode for these
    # (file_operations._pattern_has_regex_newline) — per-line scanning can't
    # match across lines, so fail OPEN to rg.
    try:
        from tools.file_operations import _pattern_has_regex_newline
        if _pattern_has_regex_newline(pattern):
            return None
    except Exception:
        if "\n" in pattern:
            return None
    try:
        rx = regex_module.compile(pattern)
    except _re.error:
        return None

    root = Path(resolved_root)
    try:
        root_is_file = root.is_file()
        if not root_is_file and not root.is_dir():
            return None
    except OSError:
        return None

    fetch_limit = limit + offset  # rg lane: `| head -n fetch_limit`

    def glob_ok(fp: Path) -> bool:
        if not file_glob:
            return True
        rel = _emit_path(root_input, root, root_is_file, fp)
        return (fnmatch.fnmatch(rel, file_glob)
                or fnmatch.fnmatch(fp.name, file_glob))

    # Raw rows WITHOUT guard verdicts: the rg pipeline guards PAGE rows
    # only (emit -> head -> page-slice -> guard-filter). Guarding every
    # scanned file during the walk measured SLOWER than rg (161 guard
    # calls vs ~5) and is unfaithful to that order. The walk collects
    # raw matches; the guard runs at envelope time, memoized per unique
    # page path.
    content_rows: list[tuple[str, int, str]] = []
    file_rows: list[str] = []
    count_rows: list[tuple[str, int]] = []  # (path, n)
    scan_stats = {"bytes": 0}

    def handle_file(fp: Path) -> bool:
        """Process one candidate file. Returns False when the walk window
        is full (content/files modes only)."""
        if fp.suffix.lower() in _SKIP_SUFFIXES:
            return True
        if not glob_ok(fp):
            return True
        emitted = _emit_path(root_input, root, root_is_file, fp)
        if output_mode == "files_only":
            # Only list files that actually contain a match (rg -l
            # semantics) — a walk hit is not a match.
            has_match = False
            try:
                for _no, line in _iter_lines(fp, scan_stats):
                    if rx.search(line):
                        has_match = True
                        break
            except OSError:
                has_match = False
            if has_match:
                file_rows.append(emitted)
                if len(file_rows) >= fetch_limit:
                    return False
            return True
        if output_mode == "count":
            n = 0
            try:
                for _no, line in _iter_lines(fp, scan_stats):
                    if rx.search(line):
                        n += 1
            except OSError:
                n = 0
            if n:
                count_rows.append((emitted, n))
            return True
        # content mode
        try:
            for no, line in _iter_lines(fp, scan_stats):
                if rx.search(line):
                    content_rows.append((emitted, no, line))
                    if len(content_rows) >= fetch_limit:
                        return False
        except OSError:
            pass
        return True

    try:
        if root_is_file:
            handle_file(root)
        else:
            files_scanned = 0
            for dirpath, dirnames, filenames in os.walk(root):
                # skip hidden dirs in-place so os.walk never descends
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                dirnames.sort()
                keep_going = True
                for fn in sorted(filenames):
                    if fn.startswith("."):
                        continue
                    keep_going = handle_file(Path(dirpath) / fn)
                    files_scanned += 1
                    if not keep_going:
                        break
                # Walk budget: bounded scans fail OPEN to rg (perf law —
                # pure-Python loses to Rust past small trees; also bounds
                # files_only/count modes which lack the early window-exit).
                if files_scanned >= _WALK_BUDGET_FILES \
                        or scan_stats["bytes"] >= _WALK_BUDGET_BYTES:
                    return None
                if not keep_going:
                    break
    except OSError:
        return None

    # Zero matches: rg's lane adds a diagnostic probe for this case
    # (similar-path / hidden-only-match hints). Fail OPEN so those hints
    # keep working — an empty fast-lane envelope would suppress them.
    if not content_rows and not file_rows and not count_rows:
        return None

    # ── Envelope: EXACT rg-lane pipeline order (search_tool) ──────────
    # rg lane: rg emits raw rows (windowed by `head -n limit+offset`) ->
    # to_dict page = matches[offset:offset+limit] -> _filter_read_blocked
    # on the PAGE -> redact page -> to_dict(total = raw window count).
    # So: total_count counts raw windowed rows (blocked included), the
    # page can SHRINK when rows are filtered (later rows never slide in),
    # and blocked rows consume page slots. Guard verdicts are computed
    # HERE, memoized per unique page path.
    guard_memo2: dict[str, bool] = {}

    def allowed2(key: str) -> bool:
        v = guard_memo2.get(key)
        if v is None:
            v = guard_fn(key, task_id) is None
            guard_memo2[key] = v
        return v

    if output_mode == "files_only":
        window = file_rows[:fetch_limit]
        page = window[offset:offset + limit]
        kept = [p for p in page if allowed2(p)]
        omitted = len(page) - len(kept)
        env: dict = {"total_count": len(window)}
        if kept:
            env["files"] = kept
        if omitted:
            env["_omitted"] = _OMITTED_MSG.format(omitted)
        return env

    if output_mode == "count":
        # rg -c has no pagination concept (no offset slice in the rg lane);
        # every raw row is the page.
        window = count_rows[:fetch_limit]
        kept = {p: n for p, n in window if allowed2(p)}
        omitted = len(window) - len(kept)
        env = {"total_count": sum(n for _p, n in window)}
        if kept:
            env["counts"] = kept
        if omitted:
            env["_omitted"] = _OMITTED_MSG.format(omitted)
        return env

    # content mode: page slice FIRST, then filter/redact the page
    window = content_rows[:fetch_limit]
    page = window[offset:offset + limit]
    kept = [(p, no, redact_fn(text[:_CONTENT_CLAMP]))
            for p, no, text in page if allowed2(p)]
    omitted = len(page) - len(kept)
    env = {"total_count": len(window)}
    if kept:
        if len(kept) >= _DENSIFY_MIN_MATCHES:
            env["matches_format"] = _MATCHES_FORMAT
            env["matches_text"] = _densify(kept)
        else:
            env["matches"] = [
                {"path": p, "line": no, "content": text} for p, no, text in kept
            ]
    if omitted:
        env["_omitted"] = _OMITTED_MSG.format(omitted)
    return env


def _densify(rows) -> str:
    """Mirror SearchResult._densify_matches: path-grouped, rstrip content."""
    lines: list[str] = []
    current: Optional[str] = None
    for path, line_no, content in rows:
        if path != current:
            lines.append(path)
            current = path
        lines.append(f"  {line_no}: {content.rstrip()}")
    return "\n".join(lines)
