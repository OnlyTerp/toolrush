# ToolRush v2 — delivered implementation and evidence

## Result

ToolRush is now a **low-overhead execution layer**, not a second, less-correct implementation of search. It removes shell overhead where the host can safely do the operation directly, batches explicitly independent reads through one RPC, preserves normal tool authority/result handling, and keeps stateful work behind barriers.

Installed in `C:/dev/AppData/Local/hermes/hermes-agent` with the persistent user plugin at `C:/dev/AppData/Local/hermes/plugins/toolrush`.

**Activation state:** exercised successfully in fresh installed Hermes processes. Existing gateway/session processes were deliberately **not restarted or hot-patched**. They must restart after active work is idle to pick up v2; starting another chat in an old gateway is not sufficient.

## Original intent recovered

Direct human statements, not the prior model's summary:
- `dev-session-1`, message `481546`: solve tool-call latency architecturally so fast models are not slowed by tools.
- Same session, `489745`: move the bottleneck back to model tokens/sec, not tool calls/file lookups.
- `dev-session-3`, `546047`: maximize parallel calls without reducing quality.
- `dev-session-2`, `523063`: stay available through updates.

Full quoted reconstruction and prior-art comparison: `intent.md`, `intent-research.md`, `design.md`.

## What changed

1. **One search engine, accelerated transport.** Removed the production Python `os.walk`/`re` shortcut. Direct `rg.exe` execution preserves real ignore files, regex grammar, context, and configuration; bounded capture avoids Bash+head overhead. Native Windows reads reuse the upstream bounded reader, normal access guards, binary/document routing, and output assembler. No result cache was added.
2. **Correct results before speed.** Fixed JSON-breaking text appended after search results; pagination now uses stable content order and a sentinel proving more results exist. Regex backslashes and leading hyphens stay literal arguments; CRLF and final unterminated lines get consistent handling.
3. **Real programmatic parallelism.** `from hermes_tools import parallel` works through local `execute_code` RPC. A batch contains 1–16 enabled read operations, runs at most four workers, and returns input order. Authentication, the enabled-tool set, 50-call budget, current cell identity, and retirement remain enforced. Whole invalid batches are rejected before dispatch. No writes or terminal calls are admitted.
4. **Correct warm-shell transport.** The old plugin returned before the environment snapshot completed and buffered/truncated output. The replacement streams through an OS pipe with bounded parser memory, waits for a filtered atomic snapshot commit, preserves exit status/cwd/exports, and kills its command tree on cancellation. No command is retried after submission. Busy/unsupported/background cases keep the existing backend.
5. **Safer existing scheduler.** Kept the native segmented scheduler instead of building a competing executor. Terminal classification now refuses hidden writes such as `wget`, branch creation, `curl -o`, `sed w`, env-wrapped scripts, and shared cwd changes. Admission is not approval: refused acceleration still takes the regular sequential path.
6. **Update survival.** The plugin stores hash-verified helper sources and 25 function-scoped compatibility patches outside the upstream checkout. A compatible update restores functions in memory, preserving imported references and live globals. Unknown touched-function or helper drift produces a degraded warning rather than overwriting new upstream code. All four lanes were restored in a disposable update simulation without changing installed file hashes.
7. **Diagnostics and rollback.** Plugin `doctor.py --smoke`, per-lane gates, a master `toolrush.enabled: false`, source preimages, payload hashes, tests, and reproducible benchmark scripts are included.

## Measured performance

Measurements are local tool operation wall time, **not model-inclusive turn speed**. Raw samples include the first sample separately and warm median/p95. File benchmarks alternate on/off on real installed repository files, with the plugin loaded, 16 warm samples per path. Results were parsed as strict JSON; content-search/read envelopes matched. File-discovery order is explicitly unordered and is tested as such.

### Compatible fallback shell path versus v2 native path

| Real workload | Shell median | Native median | Native p95 | Ratio |
|---|---:|---:|---:|---:|
| Read 100 source lines | 255.23 ms | 4.44 ms | 7.05 ms | 57.52x |
| Read page of large Python source | 256.80 ms | 7.17 ms | 9.03 ms | 35.83x |
| Search one source file | 183.43 ms | 26.88 ms | 32.96 ms | 6.82x |
| Search repository source tree | 187.23 ms | 34.16 ms | 47.98 ms | 5.48x |
| Context search | 182.67 ms | 27.85 ms | 46.23 ms | 6.56x |
| No-match search including diagnostics | 455.28 ms | 96.51 ms | 110.14 ms | 4.72x |
| File discovery | 224.66 ms | 69.15 ms | 91.34 ms | 3.25x |

These ratios are **not claims against an already-enabled v1 native reader**. V1 already bypassed some reads through its plugin. Its Python search could also be faster on a tiny fixture because it implemented fewer semantics; that is not an acceptable correctness baseline.

### Already-fast tools: sequential RPC versus new read batch

Paired real TCP RPC, generated client, normal installed dispatch, 12 warm samples per path:

| Workload | Sequential | Parallel | Ratio |
|---|---:|---:|---:|
| Four source searches | 108.14 ms | 52.61 ms | 2.06x |
| Mixed reads/searches | 65.12 ms | 45.32 ms | 1.44x |
| Four tiny native reads | 15.09 ms | 15.45 ms | 0.98x — slight regression |

A separate **controlled** 50-ms wait plus actual reads measured 218.64 → 65.41 ms (3.34x), demonstrating overlap. It is not a real network speed claim. Do not thread trivial reads merely to inflate concurrency.

### Terminal truth, including the regression versus the unsafe old shortcut

24 warm samples, separate processes, real `LocalEnvironment.execute`:

| Workload | Stock | Old plugin | Repaired plugin |
|---|---:|---:|---:|
| Builtin command | 110.14 ms | 44.31 ms | 70.48 ms |
| Python process | 168.19 ms | 107.63 ms | 108.98 ms |
| Git process | 167.74 ms | 69.88 ms | 108.96 ms |

The repaired terminal remains faster than stock but can be slower than the old plugin because completion now includes a synchronous, correct state commit. Latest p95 was 72.09/165.53/167.71 ms respectively. Windows spawn/load variability is visible in the samples; these terminal runs were not interleaved. No claim of universal improvement or a 10,000x end-to-end win.

## Verification

- **206 unique focused/regression cases passed, zero failed, zero skipped.** The combined 205-case suite passed in 77.73 seconds; one additional post-update doctor regression also passed. Deduplicated from `all-focused-final.xml`, `compat-final.xml`, and `rpc-final.xml` in `unique-regressions.json`.
- **Five negative controls fail for the intended reason:** native read disabled, native search disabled, parallel workers serialized, unsafe admission restored, snapshot commit removed. Each exited 1 with a real failing assertion; installed source hashes were unchanged. Controls are isolated processes, not edits to live code.
- **Fresh installed `execute_code`** ran four parallel reads and returned `TOOLRUSH-INSTALLED-E2E`, exit 0, `tool_calls_made: 4`.
- **Real plugin boot** through installed `PluginManager._load_plugin` confirmed the default enabled entry, all four ready lanes, a warm-shell export/readback roundtrip, and generated RPC `TOOLRUSH-BOOT-OK` with two tool calls, exit 0 (`boot-proof.json`).
- **Doctor** verified five helper hashes and four compatible lanes; its real generated-client smoke returned `TOOLRUSH-DOCTOR-OK`, exit 0, two tool calls.
- **Update simulation** restored files/RPC/admission/snapshot (15/5/1/4 functions), exercised reads/search/generated RPC, and verified installed hashes unchanged.
- **Broad file/search baseline is not green:** 441 collected, the exact same 43 failing IDs and 62 skips before/after; no new failures. Mostly Windows/POSIX assumptions and prior unrelated defects. `regression-comparison.json` records exact sets, not just counts.
- **RPC/kernel neighbors:** 50 passed, two Windows-environment failures, 16 skips. Both failures were reproduced with original RPC functions in memory (`rpc-baseline-control.xml`), not attributed away by assumption.
- Fresh independent native/admission review supplied 19 boundary checks and 93 admission cases; parent reran all four reviewer scripts, all exited 0 (`reviewer-final/parent-verified.json`). Its CRLF consistency note was fixed. The compatibility loader received a separate fresh review, no demonstrated blockers (`compat-review.md`).

### Scope corrections during validation

The original contract preceded implementation. Its detailed implementation expanded to cover real RPC batching and compatible update persistence after original intent was recovered. Stale tests that required malformed post-JSON hints, unsafe `cd` concurrency, or shell command-text observation were corrected explicitly; shell-observer tests force the shell lane, not skip behavior. The final combined run exposed a test-order issue: neighboring agent tests reload LocalEnvironment, leaving test fixtures holding an obsolete class identity. Fixtures now construct the current installed class; the production backend-isolation check was not weakened. A final doctor regression proved that post-update smoke must boot the plugin before calling generated RPC; it failed on the old doctor and passed after that fix. No existing broad baseline failures were relabeled PASS.

## Contract verdict — expect(9)

| ID | Verdict | Evidence |
|---|---|---|
| VAL-INTENT-01 | PASS | raw message IDs + intent documents |
| VAL-BASE-02 | PASS with recorded baseline red | inventory, baseline command/exit/XML |
| VAL-DESIGN-03 | PASS | profiler, direct prior-art research, architecture |
| VAL-CORRECT-04 | PASS | differential, paging, strict JSON, live handlers |
| VAL-SAFE-05 | PASS for changed boundaries | guards, admission, snapshots, cancellation, authority tests |
| VAL-NEG-06 | PASS | five genuine assertion failures + unchanged hashes |
| VAL-PERF-07 | PASS on named workloads | paired samples, regressions explicitly disclosed |
| VAL-INTEGRATE-08 | PASS in fresh installed processes | E2E, doctor, unchanged failure sets, update simulation |
| VAL-DELIVER-09 | PASS | independent reviews, local release bundle, doctor/runbook/rollback |

**Delivered code and proof; live gateway activation remains pending by design.** No public push, no provider smoke-test spend, no unrelated profile changes, no gateway interruption.

## Remaining limits

- Model/network latency, remote tool servers, rate limits, and model choice to issue parallel calls remain external bottlenecks.
- General arbitrary-shell compatibility is not claimed for the warm broker; detected unsupported cases fall back. Existing fallback process-tree problems are not magically fixed by ToolRush.
- Local RPC batches only; remote file RPC does not expose `parallel`.
- Four workers is a deliberate tested bound, not an unlimited concurrency promise. No speculative tools, stale content cache, invented API, or bypassed approvals.
- Unknown upstream changes require a compatibility review. The updater is not forced to run stale functions.
- No running gateway was restarted. Use the installed runbook when active sessions are idle.

## Entry points

- Runbook: `C:/dev/AppData/Local/hermes/plugins/toolrush/README.md`
- Doctor: `C:/dev/AppData/Local/hermes/plugins/toolrush/doctor.py --smoke`
- Local source/evidence bundle: `C:/dev/toolrush/v2/`
- Working evidence: `C:/dev/.operator/toolrush-v2/`
