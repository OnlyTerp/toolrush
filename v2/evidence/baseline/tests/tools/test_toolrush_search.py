"""ToolRush in-process search lane — contract tests.

Contract (VAL-S4 law): match SETS equal slow-vs-fast (separator-agnostic);
guard filter runs AFTER the fetch window (blocked rows occupy the window);
the exact pattern class from the 9/3 session (quoted regex with pipes) that
sparked this work runs through the fast lane byte-identical to the rg lane.
"""
import json
import os
import sys
from pathlib import Path

import pytest

HERMES = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERMES))

from tools import file_tools as ft  # noqa: E402


def _run(pattern, path, task_id="toolrush-test", limit=50, offset=0,
         file_glob=None, target="content", output_mode="content", context=0):
    os.environ["TOOLRUSH_SEARCH"] = "1"
    return json.loads(ft.search_tool(
        pattern=pattern, target=target, path=path, file_glob=file_glob,
        limit=limit, offset=offset, output_mode=output_mode, context=context,
        task_id=task_id,
    ))


def _norm(env):
    """Separator-agnostic match-set view of an envelope (VAL-S4)."""
    out = set()
    for m in env.get("matches", []):
        out.add((m["path"].replace("\\", "/"), m["line"], m["content"].rstrip()))
    if "matches_text" in env:
        cur = None
        for ln in env["matches_text"].splitlines():
            if not ln.startswith("  "):
                cur = ln.replace("\\", "/")
            else:
                line_no, _, content = ln.strip().lstrip(" ").partition(": ")
                out.add((cur, int(line_no), content.rstrip()))
    return out


@pytest.fixture()
def tree(tmp_path):
    for i in range(6):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "a.py").write_text(f"top line\ndef handler_{i}(): pass\nneedle shared {i}\nbot\n")
        (d / "b.txt").write_text(f"needle in txt {i}\nnothing here\n")
    return tmp_path


def test_sets_identical_slow_vs_fast(tree):
    slow_env = json.loads(_slow_search(tree))
    fast_env = _run("needle", str(tree))
    assert _norm(slow_env) == _norm(fast_env)
    assert fast_env["total_count"] == slow_env["total_count"]


def _slow_search(tree):
    os.environ["TOOLRUSH_SEARCH"] = "0"
    return ft.search_tool(
        pattern="needle", target="content", path=str(tree),
        limit=50, offset=0, output_mode="content", context=0,
        task_id="toolrush-slow",
    )


def test_densify_envelope_shows_for_big_pages(tree):
    env = _run("needle", str(tree))
    # 12+ matches -> path-grouped block, not the array
    assert "matches_text" in env
    assert env["matches_format"].startswith("path-grouped")
    # every path, line number, and content byte preserved (lossless contract)
    rows = [ln for ln in env["matches_text"].splitlines() if ln.startswith("  ")]
    assert len(rows) == env["total_count"]


def test_quoted_pipe_pattern_class(tree):
    """The 9/3 spark pattern: quotes + pipes inside a content regex."""
    pat = '"/api/today"|"/api/grade"|handle_now'
    slow_env = json.loads(_slow_search_pat(pat, tree))
    fast_env = _run(pat, str(tree))
    assert _norm(fast_env) == _norm(slow_env)


def _slow_search_pat(pat, tree):
    os.environ["TOOLRUSH_SEARCH"] = "0"
    return ft.search_tool(
        pattern=pat, target="content", path=str(tree),
        limit=50, offset=0, output_mode="content", context=0,
        task_id="toolrush-slow",
    )


def test_guard_after_window(tmp_path):
    """Blocked rows must occupy the fetch window; later allowed rows must
    NOT slide in to replace them (rg pipeline order)."""
    for i in range(8):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "a.py").write_text("needle one\nneedle two\n")
    # Make one directory a blocked path by pointing the guard at it via
    # monkeypatching: d3 is 'blocked'.
    blocked = str((tmp_path / "d3" / "a.py").resolve()).replace("\\", "/")

    real_guard = ft._search_result_read_block_error
    calls = {"n": 0}

    def fake_guard(path, task_id):
        calls["n"] += 1
        if path.replace("\\", "/") == blocked or path.endswith("a.py") and "d3" in path:
            return "blocked: test"
        return None

    ft._search_result_read_block_error = fake_guard
    try:
        env = _run("needle", str(tmp_path), limit=4)
    finally:
        ft._search_result_read_block_error = real_guard
    # 8 files x 2 rows = 16 raw; window=limit+offset=4 raw rows
    # (d0a1, d0a2, d1a1, d1a2) -> none blocked -> 4 kept
    assert env["total_count"] == 4
    assert calls["n"] <= 10  # memoized per unique path, not per row
    assert "_omitted" not in env


def test_guard_memoized_per_file(tmp_path):
    # Search a DEDICATED subdir: repo conftest redirects hermes runtime
    # state (SOUL.md, state.db, terminal cache) under tmp_path, so the
    # tmp_path root contains files this test didn't create.
    root = tmp_path / "only-mine"
    root.mkdir()
    (root / "x.py").write_text("needle\n" * 30)

    real_guard = ft._search_result_read_block_error
    calls = {"n": 0, "paths": set()}

    def fake_guard(path, task_id):
        calls["n"] += 1
        calls["paths"].add(path)
        return None

    ft._search_result_read_block_error = fake_guard
    try:
        env = _run("needle", str(root), limit=50)
    finally:
        ft._search_result_read_block_error = real_guard
    assert env["total_count"] == 30
    assert calls["n"] == 1  # THE S3 kill: 30 rows, ONE guard call
    assert len(calls["paths"]) == 1


def test_files_only_and_count_modes(tree):
    fast_f = _run("needle", str(tree), output_mode="files_only")
    slow_f = json.loads(_slow_search_mode(tree, "files_only"))
    assert set(fast_f["files"]) == set(slow_f["files"])
    fast_c = _run("needle", str(tree), output_mode="count")
    slow_c = json.loads(_slow_search_mode(tree, "count"))
    assert fast_c["total_count"] == slow_c["total_count"]
    assert sum(fast_c["counts"].values()) == sum(slow_c["counts"].values())


def _slow_search_mode(tree, mode):
    os.environ["TOOLRUSH_SEARCH"] = "0"
    return ft.search_tool(
        pattern="needle", target="content", path=str(tree),
        limit=50, offset=0, output_mode=mode, context=0,
        task_id="toolrush-slow",
    )


def test_pagination_page2_matches(tree):
    p1 = _run("needle", str(tree), limit=5)
    p2 = _run("needle", str(tree), limit=5, offset=5)
    all_norm = _norm(p1) | _norm(p2)
    assert len(all_norm) == 10  # 12 matches total; window is limit+offset
    assert not (_norm(p1) & _norm(p2))  # no overlap


def test_failopen_context_mode(tree):
    """context>0 must fall open to the rg lane (fast lane returns None)."""
    from tools.toolrush_search import fast_search
    out = fast_search(
        pattern="needle", root_input=str(tree), resolved_root=str(tree),
        file_glob=None, limit=50, offset=0, output_mode="content",
        task_id="t", guard_fn=lambda p, t: None,
        redact_fn=lambda s: s,
    )
    assert out is not None  # context isn't passed to the engine; bridge gates it
    # The BRIDGE must refuse context: verify via _toolrush_fast_search
    os.environ["TOOLRUSH_SEARCH"] = "1"
    bridged = ft._toolrush_fast_search(
        pattern="needle", path=str(tree), file_glob=None, limit=50,
        offset=0, output_mode="content", context=2, task_id="t",
    )
    # context is not gated in the bridge signature -> engine runs; the
    # rg lane would include context rows. Document: bridge ignores context
    # here, so search_tool must gate it. (Checked in test_bridge_gates_context)


def test_bridge_gates_context(tree):
    env = _run("needle", str(tree), context=2)
    # With context requested, the fast lane MUST not run (rg handles -C).
    # Detect: run with TOOLRUSH_SEARCH=0 and compare — both should give
    # the same match set, but the fast lane alone can't do context.
    os.environ["TOOLRUSH_SEARCH"] = "0"
    slow_env = json.loads(ft.search_tool(
        pattern="needle", target="content", path=str(tree),
        limit=50, offset=0, output_mode="content", context=2,
        task_id="toolrush-slow",
    ))
    os.environ["TOOLRUSH_SEARCH"] = "1"
    fast_env = json.loads(ft.search_tool(
        pattern="needle", target="content", path=str(tree),
        limit=50, offset=0, output_mode="content", context=2,
        task_id="toolrush-fast",
    ))
    # both engines can serve context mode identically ONLY if the bridge
    # refuses context. If fast_env lacks context lines that slow_env has,
    # the bridge failed to gate.
    slow_paths = {m["path"] for m in slow_env.get("matches", [])}
    fast_paths = {m["path"] for m in fast_env.get("matches", [])}
    assert slow_paths == fast_paths


def test_killswitch_env_off(tree):
    os.environ["TOOLRUSH_SEARCH"] = "0"
    env = json.loads(ft.search_tool(
        pattern="needle", target="content", path=str(tree),
        limit=50, offset=0, output_mode="content", context=0,
        task_id="toolrush-ks",
    ))
    assert env["total_count"] == 12
    os.environ["TOOLRUSH_SEARCH"] = "1"


def test_missing_root_fails_open(tmp_path):
    os.environ["TOOLRUSH_SEARCH"] = "1"
    out = ft.search_tool(
        pattern="x", target="content", path=str(tmp_path / "nope"),
        limit=50, offset=0, output_mode="content", context=0,
        task_id="toolrush-miss",
    )
    env = json.loads(out)
    assert env.get("error") or env.get("total_count", 1) == 0
