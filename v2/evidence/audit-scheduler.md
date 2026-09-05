# ToolRush Scheduling/Parallelism Audit — hermes-agent (read-only)

- Repo: `C:/dev/AppData/Local/hermes/hermes-agent`
- Baseline HEAD: `63279301bcbdc185c1b07b98a9312eb0c862f26d` (verified via `git log -1 --format=%H`), working tree dirty: 28 porcelain entries at audit start, 30 at end (sibling lanes active mid-session: `tools/file_tools.py` modified at 16:56 local, +66 insertions — re-verified the `fast_search` wiring citation at `tools/file_tools.py:2633` after the change; core audit files `tool_dispatch_helpers.py`/`tool_executor.py`/`run_agent.py`/`chat_completions.py` untouched since 02:04). This audit modified no repo files.
- Method: source reading of live working tree + pure-function probes + a stub-agent executor probe (real executors, real file I/O, `_invoke_tool` = `open().read()`). No repo files modified; no paid models; no runtime config touched.
- Contract: `C:/dev/.operator/toolrush-v2/validation-contract.md` (VAL-DESIGN-03 evidence here; no implementation performed).

## 1. How batches are actually planned and executed (verified chain)

1. **Entry / dispatch selection** — `run_agent.py:9103-9145` (`_execute_tool_calls`):
   - ≤1 call → sequential. Otherwise `_plan_tool_batch_segments(tool_calls, execution_cwd=active_env.cwd)` (9124-9127).
   - Single all-parallel plan → `_execute_tool_calls_concurrent`; single sequential plan → sequential; mixed → `agent.tool_executor.execute_tool_calls_segmented` (9129-9143).
2. **Planner** — `agent/tool_dispatch_helpers.py:403-563` (`_plan_tool_batch_segments`): splits the batch into *maximal contiguous runs* of parallel-safe calls vs sequential barriers, preserving the model's original order. Admission rules (all verified against source):
   - `_NEVER_PARALLEL_TOOLS = {"clarify"}` (line 45) → barrier. Unparseable/non-dict args → barrier (462-479).
   - Tool-search bridge unwrap: admission decided on the *underlying* tool (`_peel_bridge_call`, 377-400).
   - Whitelists: `_PARALLEL_SAFE_TOOLS` (48-68: read_file, search_files, web_search, web_extract, session_search, skill_view, skills_list, vision_analyze, read_terminal, ha_*, honcho_*, image_generate, read_window_below, cortex_recall), `_PARALLEL_SAFE_BRIDGE_LOOKUPS = {tool_search, tool_describe}` (127), MCP opt-in via `is_mcp_tool_parallel_safe` (111-121, 543-548).
   - Path-scoped tools (76-80): readers `{read_file, search_files}`, writers `{write_file, patch}`. Scope extraction canonicalizes via `normcase(realpath(abspath))` (579-592); V4A `patch(mode="patch")` scopes from patch-body file headers, not the decoy `path=` (616-617); `search_files` without `path` reserves `.` as reader (622-628). Conflict rule (499-510): a call conflicts only when *either* side is a writer and paths overlap (`_paths_overlap` = component-prefix, 661-677). **Reader↔reader overlap stays parallel.**
   - Read-only terminal admission (514-540): `_is_readonly_terminal_command` (190-238) must classify the whole command; then the terminal reserves its cwd subtree as a *reader*.
3. **Execution** — `agent/tool_executor.py`:
   - `execute_tool_calls_concurrent` (1218+): one `DaemonThreadPoolExecutor(max_workers=min(len(calls), 32))` per batch (`_MAX_TOOL_WORKERS = 32`, line 124; `_max_workers_for_tool_batch` 325-335; submit 1650-1670). Contextvars + thread-locals propagated (`daemon_pool.py:49-66` `copy_context()`, plus `propagate_context_to_thread` at 1662).
   - **Start-order gate** `_begin_in_order` (1382-1428): workers serialize *dispatch* by submit order (`next_start_order >= order`); bounded wait `min(_START_ORDER_GATE_TIMEOUT_S=120, batch_timeout/2)` (133, 1380); on expiry proceeds out of order; `batch_abandoned` short-circuits parked workers.
   - **Authorization gate** `_ConcurrentToolAuthorizationGate` (503-580): serializes approval prompts; lock bound = `human_wait_ceiling()` (143-165); human-approval seconds excluded from the batch deadline at the source (`excluded_seconds`, 577-580), consumed in the wait loop (1716-1719, 1737-1740).
   - Batch wait loop (1706-1808): 5 s poll; deadline default 420 s (`_DEFAULT_CONCURRENT_TOOL_TIMEOUT_S`, 128); on deadline → `f.cancel()`, `_abandon_batch()`, per-thread interrupt fan-out (1741-1770); on user interrupt → cancel pending, 3 s grace (1778-1794); heartbeat ~30 s (1797-1808). Shutdown: `wait=not abandon_executor, cancel_futures=abandon_executor` (1809-1823) — abandoned wedged workers are left detached by design (daemon threads, docstring `tools/daemon_pool.py:1-33`).
   - **Result materialization is strictly in original order**: main thread iterates `enumerate(parsed_calls)` (1832) and appends one `tool` message per call (1982). There is **no** `sorted()` reordering (an earlier working note claiming `sorted(results, key=index)` is wrong). Timeout synthesis (1845-1861), cancelled/thread-missing synthesis (1863-1892) guarantee exactly one result per `tool_call_id`. Hard interrupt fallback `_append_cancelled_tool_results` (2064-2081).
   - `execute_tool_calls_sequential` (2084+): one call per future on a process-wide `DaemonThreadPoolExecutor(max_workers=1)` (879-889); deadline = `resolve_timeout("tools.sequential_call", default=concurrent timeout)` (893-913); deliberately not `run_bounded_sync` (dynamic deadline extension while approvals open, 901-906).
   - `execute_tool_calls_segmented` (3018-3080): runs segments strictly in order, `finalize=False` per segment, turn-level budget + /steer once (3072-3080), flush gate at each segment boundary aborts the turn on persistence failure (3065-3068).
4. **Wire** — `agent/transports/chat_completions.py`: `parallel_tool_calls: true` sent only to a fail-closed allowlist currently containing exactly one provider, `"custom:inco"` (38-40, 46-63), wired at 682-687 and 918-923; Anthropic denylisted (41-43).
5. **ToolRush fast lane** — `tools/toolrush_search.py` (319 lines) exists and is wired inside `search_tool` at `tools/file_tools.py:2633` (`fast_search`, fail-open to rg; kill-switch `TOOLRUSH_SEARCH=0` / `toolrush.fast_search=false`). It is a stateless in-process walk (no index/cache file), invisible to the scheduler: admission is via `search_files` ∈ `_PATH_SCOPED_READERS`.

## 2. Measured behavior (exact commands, real exit codes)

```
cd C:/dev/AppData/Local/hermes/hermes-agent
.venv/Scripts/python.exe -m pytest tests/run_agent/test_tool_batch_segmentation.py tests/run_agent/test_parallel_terminal_and_wire.py -q --no-header
→ "57 passed in 6.08s", exit 0
```

Planner admission probes (pure functions, heredoc python, exit 0):

| Batch | Plan produced |
|---|---|
| `[read a.txt, write b.txt, read c.txt]` | `parallel:3` (one run — **no global write barrier**) |
| `[read×4, write w.txt, read×4]` (disjoint paths) | `parallel:9` |
| `[terminal rg -n foo ., terminal git status --porcelain, terminal rg -n bar src]` | `parallel:3` (read-only terminals parallel-admitted) |
| `[terminal rg -n foo ., terminal git add -A && git commit -m x]` | `sequential:2` (classifier rejects git write → barrier, order preserved) |
| `[read same.txt, write same.txt, read same.txt]` | `sequential:3` (RAW/WAR/WAW ordering enforced) |
| `[write sub/x.txt, search_files path=sub]` | `sequential:2` (write→read same-subtree race prevented) |

Classifier probes (exit 0): `rg -n x .` → True; `cd /tmp && ls` → True; `echo hi > out.txt` → False; `awk '{print > "out.txt"}' in.txt` → False; `bash -c 'ls'` → False; **`env FOO=1 python -c 'print(1)'` → True (gap, §3.1)**; **`wget https://example.com/file.zip` → True (gap, §3.2)**; **`ssh-keygen -t ed25519` → True (gap, §3.3)**.

Perf probe (`.venv/Scripts/python.exe C:/dev/AppData/Local/Temp/toolrush-probe-perf.py`, exit 0; real executors, stub agent, `_invoke_tool` = real `open().read()`):
- First call in a fresh process (import + executor construction): 0.39-0.44 s.
- 6 real file reads, one parallel segment: **0.010-0.011 s**; same 6 reads as 6 sequential single-call batches: **0.017 s**. Parallel path adds no measurable per-call dispatch overhead (~1.7 ms/call orchestration dominates).
- Planner cost: **855 µs per 10-call batch**; terminal classifier: **7 µs/command** (warm). Neither is a bottleneck.
- Earlier toolrush probe (pre-warmup) reported `3 real search_tool in one parallel batch: 846 ms` vs `3 sequential: 8 ms` — the 846 ms is first-call-in-process cost (engine import/init), landing on the first call; steady-state per-search is single-digit ms. The fast lane is a stateless walk — cold ≡ warm (no index/cache exists), so the "cold index vs warm cache" question has no second state to measure.

## 3. Discovered issues (evidence-cited)

1. **HIGH — `env` wrapper bypasses script-probe classification.** `_READONLY_TERMINAL_TOKENS` contains `env` (`tool_dispatch_helpers.py:144`) and `_segment_is_readonly` checks only the first token after stripping leading `VAR=` assignments (271-280); the wrapped command (`env FOO=1 python -c '<arbitrary code>'`) is never re-classified. Probed: `env FOO=1 python -c 'print(1)'` → True. Arbitrary code can write files, so it joins parallel runs and escapes the writer-reservation ordering entirely (can race a same-subtree `write_file` with no RAW/WAR/WAW barrier). Fix direction: when the accepted head token is a wrapper (`env`, and audit `nice`/`nohup`/`time`/`command` if ever added), recursively classify the remainder.
2. **MEDIUM — `wget URL` classified read-only though it writes the fetched file into cwd.** `wget` is whitelisted as a network *read* (`tool_dispatch_helpers.py:153`) and the flag filter (297-313) only rejects data/upload/output flags — the default save-to-cwd behavior is missed (probed: True). Planner treats read-only terminals as cwd-*readers* (530-537), so `wget` can silently overwrite a file concurrently with a batched `write_file` to the same subtree. Fix direction: require explicit stdout forms (`-O-`, `--output-document=-`, `-qO-`) or classify bare `wget` write-class.
3. **MEDIUM — `ssh-keygen` classified read-only for all shapes.** Whitelisted at `tool_dispatch_helpers.py:153`; `ssh-keygen -t ed25519` (probed True) writes key files into cwd. Same race class as (2). Fix direction: allow only explicit read forms (`-l`, `-F`, `-y`) or drop it.
4. **LOW — abandoned-but-running workers execute side effects with no wire record.** On batch deadline/interrupt the executor abandons: `shutdown(wait=False, cancel_futures=True)` leaves already-running daemon workers detached (`tool_executor.py:1809-1823`, `daemon_pool.py:28-32`). A worker finishing after the main loop passed its index writes `results[index]` (1594) that is never consumed (the timeout result was already synthesized, 1845-1861; the prefer-real-result race is only honored within the materialization window, 1840-1843). One-result-per-call-id and wire integrity hold; the cost is unrecorded side effects (relevant only for side-effectful MCP tools admitted parallel) and wasted work. Inherent to the daemon-pool tradeoff, documented in-source.
5. **LOW — read-only terminal cwd capture race inside a parallel segment.** `LocalEnvironment.cwd` is a shared mutable attribute (`tools/environments/local.py:2141, 2328, 2335`); `execute()` captures `cwd or self.cwd` non-atomically (`tools/environments/base.py:1480`) and `_update_cwd` writes it back per call (1408). The classifier allows `cd` inside read-only chains (`tool_dispatch_helpers.py:140`), so a batch like `[terminal "cd /a && rg x .", terminal "rg y ."]` can run the second call in `/a` if the first's `_update_cwd` lands between capture and spawn. Annoyance (wrong working directory), not corruption; both calls are still per-call `Popen` (isolated env, snapshot-sourced). The in-source comment at `base.py:1411-1413` shows the design accepts concurrent callers for reads. Fix direction: pin the planner's `execution_cwd` per submitted call, or exclude `cd`-containing commands from parallel admission.
6. **INFO — start-order gate is dispatch-order, not execution-order.** Workers queue on `next_start_order` (1382-1428) so a slow *pre-dispatch* hook (e.g. checkpoint on destructive command, 1204-1213, or a hanging `pre_tool_call` plugin) parks later workers up to `min(120 s, batch/2)`, then they proceed out of order. Bounded and self-healing (#79705); with µs-ms dispatch (measured) the cost today is nil.
7. **INFO — head-of-line at segment granularity.** Segments run strictly in order (3048-3068) and the 420 s batch deadline is per-segment (128): one straggler in a parallel segment delays every later segment and its own segment's results are synthesized at deadline. This is the price of exact side-effect ordering; the only safe relaxation is overlapping *reader-only* segments (see §4).
8. **INFO — the scheduler is starved upstream: `parallel_tool_calls` hint is effectively disabled.** The allowlist has one provider (`chat_completions.py:38-40`). Most providers never receive the hint, so models rarely emit multi-call batches — the batching machinery mostly idles. Provider verification + allowlist growth is the highest-leverage, zero-protocol-risk enablement.
9. **INFO — correction to earlier audit notes.** `[read(A), write(B), read(C)]` does **not** create 3 segments (probe: one `parallel:3` run); worker cap is **32** (not 8); gate timeout is **120 s** (not 0.5 s); results are appended in original order by the main thread (no `sorted()` step).

Verified-intact invariants (no defect found): wire order = original call order at every path; one result per tool_call_id on timeout/interrupt/segment-abort; same-path read/write ordering; write→search subtree ordering; approval serialization + deadline exclusion; contextvar/thread-local propagation (`daemon_pool.py:49-66`, `propagate_context_to_thread` 1662); interrupt fan-out releasing gate-parked workers (1760-1770); segment-boundary persistence gate (3065-3068).

## 4. Minimal compatibility-preserving architecture (proposal; parent owns design)

Keep the entire current skeleton — contiguous-run planner, path reservations, start-order gate, authorization gate, deadline exclusion, `DaemonThreadPoolExecutor`, in-order materialization. Three increments, in priority order:

1. **Classifier hardening (correctness, prerequisite to any speedup):** fix issues 1-3 (`env` recursion, `wget`/`ssh-keygen` write-class). Pure function changes in `tool_dispatch_helpers.py`; no protocol, ordering, or executor change. Guarded by existing segmentation tests + new negative cases.
2. **Upstream enablement (biggest measured win, zero scheduler risk):** grow the `_PARALLEL_TOOL_CALLS_PROVIDERS` allowlist per provider after a 400-free smoke probe; the wire param already exists and the executor already handles arbitrary batch shapes. Without model-emitted batches, nothing else matters.
3. **Reader-only segment lookahead (optional DAG-lite):** when the planner marks two adjacent segments as *reader-only with disjoint path reservations* (all calls ∈ readers/whitelist/proof-read-only terminal; no MCP; no terminal-with-`cd`), the executor may submit the next segment's calls while the current segment's stragglers run, materializing results strictly in original order (the indexed `results` array + in-order append loop already support this — only the wait loop changes from "wait for segment's futures" to "wait for union, materialize in order"). Preserves: wire order (append stays ordered), side-effect ordering (readers are commutative; writers still barrier), error/cancel semantics (same abandonment machinery, one result per call). Gate behind a config flag defaulting off; kill switch preserved. This converts the only real head-of-line case (long read straggler blocking later independent reads, §3.7) into overlap without touching write ordering.

Explicitly out of scope of the proposal: per-call deadlines replacing the batch deadline (larger change, interacts with gate/abandon semantics), and any change to result message construction.

## 5. Commands run (exact, with exit codes)

| Command | Exit |
|---|---|
| `cd C:/dev/AppData/Local/hermes/hermes-agent && git log -1 --format=%H && git status --porcelain \| wc -l` | 0 (HEAD `63279301…`, 28 dirty) |
| `.venv/Scripts/python.exe -m pytest tests/run_agent/test_tool_batch_segmentation.py tests/run_agent/test_parallel_terminal_and_wire.py -q --no-header` | 0 — `57 passed in 6.08s` |
| heredoc python: planner admission probes A1-A6 + classifier probes | 0 |
| heredoc python: `_paths_overlap` read + supplemental classifier probes (env/wget/ssh-keygen/bash -c/awk) | 0 |
| `.venv/Scripts/python.exe C:/dev/AppData/Local/Temp/toolrush-probe-perf.py` (probe script written to `%LOCALAPPDATA%/Temp`, not the repo) | 0 — warmup 0.39-0.44 s; 6-read parallel 0.010-0.011 s; sequential sum 0.017 s; planner 855 µs/batch; classifier 7 µs |
| `pytest tests/tools/test_toolrush_search.py` not re-run in full this session (suite covers fast_search; referenced only) | — |

No repository files were modified. Scratch probe lives at `C:/dev/AppData/Local/Temp/toolrush-probe-perf.py` (outside the repo).
