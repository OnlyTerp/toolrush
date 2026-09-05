# ToolRush Live Port Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Port the three proven ToolRush lab prototypes into the live hermes-agent tree behind config kill-switches, so local tool calls run 20-1000x faster with byte-identical outputs and unchanged safety guards.

**Architecture:** Each prototype lands as a fast lane INSIDE the existing handler — safety guards (device/block lists, doc extraction, approval, read-block filter) stay exactly where they are; only the byte-fetch/spawn layer underneath switches. Every lane has a config kill-switch defaulting ON, plus env overrides. Remote/docker/modal backends never touch the fast lane (local-backend gate).

**Tech Stack:** Python, live tree `C:/dev/AppData/Local/hermes/hermes-agent`, lab source `C:/dev/toolrush` (read-only reference — copy, don't import).

**Precondition (BLOCKING):** Sibling toolcap WIP is dirty in the live tree (`agent/prompt_builder.py`, `agent/tool_dispatch_helpers.py`, `agent/tool_executor.py`, `run_agent.py` + `.bak-*` files, seen 2026-09-02). Coordinate: EITHER sibling commits/stashes first, OR port lands on a branch cut after their files settle. NEVER `git stash` their WIP. Confirm with Operator which before Task 1.

---

### Task 1: Fast-read lane in `read_file_tool` (file_tools.py)

**Objective:** In-process local reads bypass the 5-shell-command path with identical output.

**Files:**
- Modify: `tools/file_tools.py` (~line 1657 `read_file_tool`, insert after doc-extraction block ~line 1762, before shell-based read path)
- Test: `tests/tools/test_toolrush_fastread.py` (new)

**Step 1: Write failing test**

```python
def test_fastread_matches_harness_byte_identical(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("l1\nl2\nl3\n", encoding="utf-8")
    from tools import file_tools as ft
    slow = ft.read_file_tool(str(f), task_id="t-slow-test")  # force slow below
    fast = ft.read_file_tool(str(f), task_id="t-fast-test")
    assert slow == fast
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/tools/test_toolrush_fastread.py -v`
Expected: FAIL — `read_file_tool` has no fast lane yet (or module missing).

**Step 2: Implement minimal fast lane**

Copy `fast_read` body from `C:\dev\toolrush\toolrush.py:60-145` into a new
`_toolrush_fast_read(path, offset, limit)` helper in `file_tools.py` (adapt:
use the module's own `normalize_read_pagination`, `get_max_line_length`;
drop the `sys.path` hack — already in-tree). Insertion logic in
`read_file_tool` AFTER the doc-extraction block, BEFORE the shell read:

```python
# ── ToolRush fast lane ──────────────────────────────────
# Local backend only: in-process open()/stat replaces the 5-shell
# round-trip. Guards above (device/block/doc/binary) already ran.
# Kill-switch: config toolrush.fast_read=false or TOOLRUSH_FASTLANE=0.
if _toolrush_fast_read_enabled() and _file_ops_uses_host_paths(_get_file_ops(task_id)):
    return _toolrush_fast_read(str(_resolved), offset, limit)
```

`_toolrush_fast_read_enabled()`: `os.environ.get("TOOLRUSH_FASTLANE","1")=="1"`
AND config `toolrush.fast_read` (default True; missing key = True). Env wins
for negative controls.

**Step 3: Run test to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/tools/test_toolrush_fastread.py -v`
Expected: PASS. Also run lab parity: outputs equal on empty file, beyond-EOF
offset, long-line clamp, BOM file (lab `toolrush.py` documents all four).

**Step 4: Negative control**

Run with `TOOLRUSH_FASTLANE=0`: same test passes via slow path; add a timing
assert — fast < 50ms, slow > 200ms on Windows (documents the win in-tree).

**Step 5: Commit**

```bash
git add tools/file_tools.py tests/tools/test_toolrush_fastread.py
git commit -m "feat(toolrush): fast-read lane in read_file_tool (1460ms->1.2ms, guards intact)"
```

---

### Task 2: Session read cache (file_tools.py, same area)

**Objective:** Mtime-keyed `(path,offset,limit)` cache so repeat reads of unchanged files cost a dict lookup.

**Files:**
- Modify: `tools/file_tools.py` (module-level `_TOOLRUSH_READ_CACHE` + lock, used inside `_toolrush_fast_read`)
- Test: extend `tests/tools/test_toolrush_fastread.py`

**Step 1: Write failing test**

```python
def test_repeat_read_hits_cache(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("x\n", encoding="utf-8")
    from tools import file_tools as ft
    a = ft.read_file_tool(str(f))
    b = ft.read_file_tool(str(f))
    assert a == b
    assert ft._toolrush_cache_stats()["hits"] >= 1
```

Run: `pytest tests/tools/test_toolrush_fastread.py::test_repeat_read_hits_cache -v`
Expected: FAIL — no cache/stats yet.

**Step 2: Implement** — copy cache block from lab `toolrush.py:46-48,76-80,98-100,143-144`:
key `(str(resolved),offset,limit)` -> `(st_mtime_ns, rendered)`. Mtime-keyed:
a write changes mtime so stale entries can never serve. Kill-switch
`toolrush.read_cache` (default True) / `TOOLRUSH_CACHE=0`.

**Step 3: Run** — full file green.

**Step 4: Staleness proof** — test: read, overwrite file, read again returns NEW
content (mtime changed -> miss). This is the anti-stale-behavior contract.

**Step 5: Commit** — `feat(toolrush): mtime-keyed session read cache`.

---

### Task 3: Persistent-shell executor (terminal local backend)

**Objective:** ONE process-wide bash for local commands; 285ms -> 12ms.

**Files:**
- Create: `tools/toolrush_exec.py` (in-tree port of lab `toolrush_exec.py` — drop `sys.path` hack, import `_find_bash` normally)
- Modify: local terminal backend execute path (`tools/environments/local.py` — the `execute` that spawns bash per command; gate: `USE_PERSIST` + local backend only)
- Test: `tests/tools/test_toolrush_exec.py` (new)

**Step 1: Write failing test**

```python
def test_persist_echo():
    from tools.toolrush_exec import toolrush_exec
    o, c = toolrush_exec("echo termbench")
    assert o.strip() == "termbench" and c == 0
```

Run: `pytest tests/tools/test_toolrush_exec.py -v` — FAIL (module missing).

**Step 2: Implement** — copy lab file verbatim minus path hack. Framing markers
`TRX{pid}{rand}_BEGIN/END`, per-call `cd` tracking, respawn-on-death,
timeout->rc 124. Wire into `local.py` execute: if persist enabled AND command
is a plain local shell invocation, route via `toolrush_exec`; stdin_data/
remote/docker paths NEVER route (fail-closed to old path).

**Step 3: Run** — green; plus compound (`echo a && echo b`), exit code
(`exit 7` -> 7), cwd (`pwd` with cwd arg) — lab selftest cases as tests.

**Step 4: Negative control** — `TOOLRUSH_PERSIST=0` routes spawn-per-call;
timing assert fast < 50ms.

**Step 5: Commit** — `feat(toolrush): persistent-shell executor for local terminal`.

---

### Task 4: In-process search + verdict memo (file_tools.py search path)

**STATUS: DONE 9/3 — landed differently than planned, for measured reasons.**

Deviations from the original design (all benchmark-driven, see
`toolrush/bench_search_live.py` + `bench_search_whole_repo.py`):
1. **Guard on PAGE, not per-file.** The planned per-file walk-time memo
   measured SLOWER than rg (161 guard calls vs ~5 page rows; 0.8x). The
   live rg pipeline guards page rows only — the restructure (walk = raw
   matches, envelope = memoized guard on unique page paths) flipped
   repo-scale searches from 0.8x to 7-8.5x.
2. **Walk budget (500 files / 32MB).** Beyond that the pure-Python walk
   ties or loses to rg's Rust scanner (158k-file repo: 1.0x) -> fail
   OPEN to rg. Small/medium trees stay 7-8.5x.
3. **Zero-match fail-open.** rg's lane adds diagnostic probes on empty
   results (similar-path/hidden-match hints); an empty fast-lane
   envelope would suppress them. 5 test failures caught this.
4. **Envelope is byte-identical** to the rg lane (window = limit+offset
   raw rows, page slice, THEN guard filter, redact, densify >=12 rows,
   _omitted parity) — enforced by 11 contract tests incl. the muse-spark
   quoted-pipe pattern class.

Files landed: `tools/toolrush_search.py` (new, 327 lines),
`tools/file_tools.py` (+98: kill-switch `_toolrush_fast_search_enabled`
[TOOLRUSH_SEARCH=0 / toolrush.fast_search:false], bridge in search_tool),
`tests/tools/test_toolrush_search.py` (new, 11 tests).
Proof: 28/28 toolrush+zero-match suites; negative control RED (2 fail);
failure sets lane-on vs lane-off IDENTICAL on the full -k search run
(12 pre-existing giant-line/macOS/hidden-path failures, lane-independent);
bench: small 8.2x, tools/ 8.5x, repo-glob 7.0x, envelopes rows-match=True.
Kill-switch default ON; needs gateway restart to take effect live.

**Original objective (historical):** Content search without rg spawn; REAL guard per unique file + task-scoped memo. 900ms -> 42ms.

**Files:**
- Modify: `tools/file_tools.py` (`search_tool` content branch) + new `tools/toolrush_search.py` (port of lab)
- Test: `tests/tools/test_toolrush_search.py` (new)

**Step 1: Write failing test**

```python
def test_search_sets_identical(tmp_path):
    for i in range(9):
        (tmp_path / f"f{i}.txt").write_text(f"top\nneedle_zed {i}\nbot\n")
    from tools import file_tools as ft
    import json
    r = json.loads(ft.search_tool(pattern="needle_zed", target="content",
                   path=str(tmp_path), output_mode="content", limit=50))
    assert r["total_count"] == 6  # i%3==0 are filler
```

Run: FAIL (no fast path; note: slow path must ALSO return 6 — if not, fix the
fixture, not the code).

**Step 2: Implement** — port lab `toolrush_search.py:55-113`. Insertion in
`search_tool` content-target branch: if enabled AND local paths, run
`fast_search`, then shape rows into the EXISTING result envelope
(`total_count` + `matches_text` path-grouped prose — the envelope stays
byte-identical; only the engine changes). Verdict memo keyed
`(normpath, task_id)` with lock. Kill-switch `toolrush.fast_search` /
`TOOLRUSH_SEARCH=0`.

**Step 3: Run** — green; match SETS identical slow-vs-fast (parse both
`matches_text`, compare as sets — comm semantics, lab VAL-S4 precedent).

**Step 4: Negative control** — `TOOLRUSH_SEARCH=0` ~= slow timing.

**Step 5: Commit** — `feat(toolrush): in-process search with memoized guard verdicts`.

---

### Task 5: Full-suite gate + evidence (NO wave-4 port — verdict was STOP)

**Objective:** Prove zero regressions and record end-to-end evidence.

**Files:** none (evidence only) + update `C:\dev\toolrush\results.md` (ToolRush repo commit).

**Step 1:** Run targeted suites:
`pytest tests/tools -q` (file/search/terminal scope). Record pass/fail.
**Step 2:** Run the three lab benches against the LIVE tree (kill-switches on):
`bench_proto.py`, `bench_term_proto.py`, `bench_search_proto.py` — record
live speedups next to lab numbers. Any lane < 50% of lab win = investigate,
do not ship that lane.
**Step 3:** Run each lane's negative control live (`TOOLRUSH_*=0`) — must
reproduce pre-port timings (proves the switch is real, not placebo).
**Step 4:** Full agent test sweep per Hermes test-runner law
(`./.venv/Scripts/python.exe -m pytest`, elevenlabs stubbed, 544+8 baseline).
New failures vs pre-port baseline = BLOCKED, report, stop.
**Step 5:** Commits: live tree per-lane commits (Tasks 1-4) + ToolRush repo
`results.md` evidence update + push `origin/main`.

---

## Risks / tradeoffs / open questions

- **Sibling toolcap collision (BIGGEST):** live tree has their dirty files in
  the exact dispatch area. Precondition gate handles it — do not start Task 1
  until resolved. (Per-action autonomy: reversible local writes are fine, but
  shared-tree collisions are NOT reversible — propose/wait was satisfied by
  Operator's "yea do it" for the plan; the branch-vs-wait call is still his.)
- **Phantom-line quirk:** lab reproduces the harness `51|` trailing quirk
  byte-for-byte. Upstream may later remove the quirk — the fast lane must then
  drop line 126 (`content += f"\n{offset+len(page)}|"`) in the same commit.
  Flagged in code comment.
- **Persistent shell state:** cwd/env persist across commands by design (that
  IS the win). A command that kills the shell (`exec`, `exit`) triggers
  respawn-on-death; document, don't "fix".
- **Search envelope:** `matches_text` prose format is preserved exactly —
  downstream parsers (including the consecutive-search guard) see no change.
- **Wave 4 (dispatch):** explicitly NOT ported — 4.44ms of safety rails,
  verdict STOP with numbers in `dispatch-verdict.md`.
- **Restart caveat:** all lanes take effect on Hermes gateway restart (running
  gateway holds old modules in memory) — same runtime law as every prior
  Hermes change. Plan the restart with Operator, don't surprise him mid-stream.
