# ToolRush — Intent Reconstruction & Prior-Art Research (2026-09-04)

Read-only research artifact for toolrush-v2 (contract: validation-contract.md, VAL-INTENT-01 / VAL-DESIGN-03 inputs). All user quotes verbatim with session/message IDs; all claims path-cited. No live-tree edits, no restarts, no config changes.

---

## 1. Original user intent — direct messages (verbatim, cited)

| # | When | Source | Verbatim |
|---|------|--------|----------|
| 1 | 09-02 18:22 | session `dev-session-1` ("reinventing tool calls"), msg **481546** | "i want to solve the bottleneck of how slow tools calls are this day and age, they are just not setup to properly take advantage of super fast ai models and often times a model could be flying but is slowed down dramatically by tool calls, we need to solve how tool calls work architecutally and invent a better system you down" |
| 2 | 09-02 (same session), msg **489745** | "do whatever it takes to create, optimize, perfect this tech to get tool calls to work so rediculously fast that the bottleneck goes back to a models tokens per second and not stupid tool calls, file lookups etc" + "make a private github for all this work ur doing btw and name it something that u think is good" |
| 3 | 09-03 18:40 | session `dev-session-2`, msg **523063** | "yes make sure the toolrush stuff i went so hard to make is live always even trhough updates and also if u wanna take a crack at inmproving toolrush after once u get inco working right and i can use it while u do that, that would be fire" |
| 4 | 09-03 20:28 | session `dev-session-3` ("Improve Hermes performance without quality loss"), msg **546047** | "now what about toolrush? can u help us do an even better job with it? the goal is to reduce latency and time things take without reducing quality but fixing the biggest bottleneck in here, tool calls and how many can be used at once in parralel, if we can Maximize the parral tool calls and push it to the limit and also at the same time completely fix them then my fast models can ACTUALLY BE FAST" |

**Reconstructed intent (four distinct asks, in user's order):**
- **A. Kill per-call tool latency** so harness overhead stops masking fast models (msgs 1–2). "Bottleneck goes back to model TPS" is the explicit success criterion.
- **B. Architectural reinvention, not micro-opts** (msg 1: "solve how tool calls work architecutally and invent a better system").
- **C. Maximize parallel tool calls to the limit, with zero quality loss** (msg 4) — a *second*, distinct axis from A: not per-call speed but batch concurrency.
- **D. Durability: live always, survives updates** (msg 3) — and a private GitHub repo for the work (msg 2; delivered: `OnlyTerp/toolrush`).

Distinguishing ambition from ask: "invent a better system" was the ambition framing; the *operational* asks A/C/D are all about the existing Hermes harness getting faster — which is what the lab actually built (make the existing dispatch cheap), not a new tool-call protocol.

## 2. Lab claims vs measured state (`C:/dev/toolrush`, commits 0184d5f…263425a)

| Claim | Measured where | Status |
|---|---|---|
| read_file 1460ms → 1.18ms (1237x); 20-read batch 32.4s → 2.8ms (11584x) | `results.md` T1/T2/P1/P2, real registry.dispatch + real handlers, N stated | **Measured in lab**, on Windows/git-bash, 83-tool registry |
| Terminal `echo` 285ms → 12.1ms (23.6x); decomposes ~8x wrap-trim + ~3x persistent shell (negative control 34.2ms) | `README.md` wave-2 VAL-T1…T6, `results.md` | **Measured in lab**, byte-identical stdout claimed |
| Search 900ms → 42ms (21.3x), match sets identical 40/40 | `README.md` wave-3 | **Measured in lab**, small-tree workload |
| Dispatch pipeline: registry 0.005ms, full path 4.44ms — verdict **STOP** (load-bearing safety rails) | `dispatch-verdict.md`, noop-handler profiling N=15–25 | **Measured**; lab's own conclusion: per-handler waves removed 99%+ of tool latency; remaining bottleneck is model TPS |
| Landed in live tree: in-process fast search + file_tools bridge | live-port plan Task 4 "STATUS: DONE 9/3"; `tools/toolrush_search.py` + `tools/file_tools.py:2589-2724` exist untracked; msg 546041 confirms restart loaded it | **Shipped** (untracked file, gateway restart 9/3 claimed at 23:33) |
| Landed as user plugin: native-read lane + warm-shell terminal lane, update-safe, kill-switches | `C:/dev/AppData/Local/hermes/plugins/toolrush/__init__.py` (425 lines), `plugin.yaml` | **Shipped** (plugin strategy, *not* the plan's Task 1–3 design); no in-tree benchmark numbers found for it |
| Fast-read + session cache + persistent exec ported into `file_tools.py`/`local.py` (Tasks 1–3) | plan Tasks 1–3; **not found in live tree** (`grep toolrush tools/environments/` → 0 hits; only search bridge in file_tools.py) | **Not ported** — superseded by the plugin's different mechanism (harness's own `_read_file_native` enabled + `LocalEnvironment._run_bash` class patch) |
| Parallel batch dispatch (segmented executor) | `agent/tool_executor.py:3018` `execute_tool_calls_segmented`, `agent/tool_dispatch_helpers.py:566` `_should_parallelize_tool_batch`, `_PARALLEL_SAFE_TOOLS` (:48), `_MAX_TOOL_WORKERS=32` (tool_executor.py:124), caller `run_agent.py:9139`; tests `tests/run_agent/test_tool_batch_segmentation.py` | **Implemented but UNCOMMITTED WIP** (part of dirty sibling toolcap work: +283/+176/+98 lines modified 09-04 02:04, after all running Hermes processes started 20:54 09-03) |

## 3. Discovered issues

1. **[high] Parallel-dispatch work (user ask C) is unverified live.** The segmented executor lives only in dirty working-tree files (git status: `M agent/tool_executor.py`, `M agent/tool_dispatch_helpers.py`, `M run_agent.py`; `?? tools/toolrush_search.py`, `?? agent/content_tool_calls.py`). No toolrush commits exist in the live repo (`git log --all --grep=toolrush` → empty). The running gateway started 20:54 09-03 (Get-Process), predating the 02:04 09-04 file mtimes — the current process cannot contain those dispatch edits, and any restart that does load them loads uncommitted code. Files: `agent/tool_executor.py:3018`, `agent/tool_dispatch_helpers.py:566`.
2. **[high] The 11,584x headline is a sequential-baseline artifact.** 32.4s baseline = 20 *sequential* reads (T2), but the harness already parallelizes batches (T3 concurrent = 7.4s, T3b persistent pool = 6.5s — `results.md:8-9,24-27`). Against the realistic concurrent baseline the honest batch win is ~2,300x, still lab-only. results.md itself warns "kill the tax, don't just parallelize it" while the README headline uses the sequential number. Not E2E-validated in any model-driven session.
3. **[medium-high] "mtime ⇒ never stale" cache claim is unsound as stated.** `toolrush.py:74-100` keys `(path,offset,limit)→(st_mtime_ns, rendered)`; README:25-26 claims "a write changes mtime so stale entries can never serve". False in general: same-mtime-ns rewrites (FAT/exFAT 2s resolution, rapid in-place rewrites), and the stat→read TOCTOU window. Lab P4 tested only overwrite-then-read; no same-mtime negative control exists.
4. **[medium] No end-to-end proof of user-visible wins.** Every number is harness-dispatch micro-benchmark latency; there is no measured token-stream session (model TPS with/without lanes). dispatch-verdict.md concedes the remaining ordering is "model TPS >> 4ms pipeline >> 1-42ms handlers" — i.e., ask A may already be at diminishing returns locally; ask C (parallelism) is where headroom remains.
5. **[medium] Two divergent port strategies coexist unconsolidated.** Plan Tasks 1–3 (copy lab `fast_read` into `file_tools.py`) were superseded by the plugin approach (enable harness's own `_read_file_native` via `ShellFileOperations._native_read_enabled` patch, `plugins/toolrush/__init__.py:77-118`; warm shell via `LocalEnvironment._run_bash` patch :298-397). A parent "go optimize harder" pass that follows the stale plan would duplicate the plugin lanes.
6. **[low] Plugin terminal lane serializes per-env under concurrency** (documented in-code, :339-344): warm-shell lock busy-waits 0.5s then cold-spawns — preserves correctness but silently drops to the 287ms path exactly when parallel tool calls (ask C) hammer the same env.
7. **[low] Lab search numbers ≠ in-tree search behavior.** In-tree redesign guards per-page not per-file, fails open to rg beyond 500 files/32MB (plan Task 4, measured 7-8.5x ⇒ ~100-130ms, not 42ms). README's 21.3x describes the lab prototype only.

## 4. Mature prior art (external, for the parent's design phase)

- **Anthropic Programmatic Tool Calling (PTC)** — Claude writes code that calls tools inside a code-execution container instead of one model round-trip per invocation; BrowseComp/DeepSearchQA +11% avg with −24% input tokens; flagship example: 20 DB lookups in one script vs 20 round-trips. Requires `code_execution_20260120`+; enabled per-tool via `allowed_callers`. Source: https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling (retrieved 09-04).
- **Anthropic Tool Search Tool** — `defer_loading: true` tools discovered on demand; ~85% token reduction (~77K→8.7K before-work context in their 50-tool example); accuracy 49%→74% (Opus 4) on MCP evals with large tool libraries. Same page + https://www.anthropic.com/engineering/advanced-tool-use (Nov 24 2025).
- **Anthropic "Code execution with MCP"** — tool defs + results can consume 50K+ tokens before an agent reads the request; presentation layer/pagination of results in code. https://www.anthropic.com/engineering/code-execution-with-mcp
- **LLMCompiler (ICML 2024, Kim et al., arXiv:2312.04511)** — canonical DAG orchestration: Planner → Task Fetching Unit → parallel Executor; latency up to 3.7x, cost up to 6.7x, accuracy up to ~9% vs ReAct. Directly comparable to Hermes's segmented executor, which is a *contiguous-run* special case (no cross-call dependency graph beyond "parallel-safe prefix runs"). https://arxiv.org/abs/2312.04511, https://github.com/SqueezeAILab/LLMCompiler
- **OpenAI function calling** — native parallel function calls plus `tool_search` deferral for large toolsets (gpt-5.4+). https://developers.openai.com/api/docs/guides/function-calling
- **Research-stage RL approaches** (ParaTool ICML 2026, PORTool, W&D "Scaling Parallel Tool Calling") — train models to emit parallel/dependency-aware calls; not production harness infrastructure; cited as evidence the *model-side* half of ask C is a known open problem. https://arxiv.org/html/2602.07359v1 et al.
- **Hermes-native facilities already present** (no custom invention needed): segmented batch executor with 32-worker pool + parallel-safe allowlist + MCP opt-in (`tool_dispatch_helpers.py`, `tool_executor.py`); built-in tool_search/tool_describe deferred-loading pair; dedup-stub cache precedent (8ms, `results.md:21-23`); `_command_cache` precedent cited by lab.

**Map to ToolRush asks:** A (per-call latency) = executor-side work, matches LLMCompiler's Executor role + Anthropic's "process, don't round-trip" thesis; C (parallel ceiling) = Task Fetching Unit role — Hermes's contiguous-run segmentation is a conservative subset of LLMCompiler's dependency DAG; the mature unexploited design here is dependency-aware (DAG) dispatch and PTC-style programmatic orchestration for multi-call fan-outs, not more per-handler micro-optimization (wave-4 STOP verdict already bounds that).

## 5. Bottom line for the parent

Direct intent = **(A)** minimize per-call tool latency until bottleneck returns to model TPS, **(B)** treat it as an architecture problem, **(C)** maximize parallel tool calls with zero quality loss, **(D)** keep it live through updates. Lab waves 1–4 are honestly measured at harness level (STOP verdict on dispatch pipeline included); three lanes shipped via plugin + search bridge; **ask C is the live frontier and currently exists only as uncommitted, unverified WIP in the exact files a sibling has dirty**; no E2E session-level measurement of any lane exists; the mtime-cache staleness proof is unsound as claimed. Any "work properly and real" pass should start by verifying/loading the dirty dispatch WIP behind its tests, then design against the DAG/PTC prior art rather than re-optimizing handlers.

### Key commands run (evidence)
- `git log --oneline -8` (live tree) → clean upstream list, no toolrush commits; exit 0
- `git status --short` (live tree) → 14 modified + 4 untracked incl. `tools/toolrush_search.py`; exit 0
- `git log --all --oneline --grep=toolrush -i` → empty (no commits); exit 0
- `grep -n "_MAX_TOOL_WORKERS\s*=" agent/tool_executor.py` → `124:_MAX_TOOL_WORKERS = 32`; exit 0
- `grep -rn toolrush tools/environments/` → 0 hits (Task 3 not ported); exit 0
- `stat -c "%y %n"` on 4 files → search lane 09-03 20:25, dispatch files 09-04 02:04, plugin 09-03 20:22; exit 0
- `Get-Process` (Hermes/python) → Hermes PIDs started 09-03 20:54; exit 0
