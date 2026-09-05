# Baseline results — 2026-09-02, real registry.dispatch + real handlers, 83 tools registered

```json
{
  "T1_single_read_dispatch_ms":  { "median": 1459.87, "p90": 1887.69 },
  "T1b_dedup_stub_ms":           { "median": 8.0,     "p90": 9.78 },
  "T2_seq_20x_read_ms":          { "per_batch_avg": 32436.4 },
  "T3_conc_20x_freshpool_ms":    { "per_batch_avg": 7419.7 },
  "T3b_conc_20x_persistpool_ms": { "per_batch_avg": 6532.3 },
  "T4_5x_search_ms":             { "per_call_avg": 810.5 },
  "T5_10x_terminal_echo_ms":     { "per_call_avg": 286.8 }
}
```

## What this says (VAL-BASE-02)

- **T1 is the headline: ~1.46s for ONE read_file dispatch** on a warm process.
  A 4KB file read should be <5ms of I/O — the other 1455ms is harness tax
  (path resolution, guards, secret-redaction scan, checkout of middleware,
  tracker bookkeeping, json round-trips, display/sanitize passes).
- **T1b proves the harness already knows the answer: 8ms stub** when the
  dedup cache hits. The 180x gap (1460 -> 8) is the prize: make the common
  path cost stub-like without lying about freshness.
- **T2 vs T3: concurrency already wins 4.4x** (32.4s -> 7.4s for 20 reads),
  and a persistent pool shaves another 12% (7.4s -> 6.5s). But per-call tax
  still dominates: 20 concurrent reads still cost 6.5s = ~325ms amortized
  per call, vs 8ms stub.
- **T4 search 810ms/call**: rg subprocess spawn + result shaping per call.
- **T5 terminal echo 287ms/call**: process spawn per call.
- T2 math check: 20 x 1460ms = 29.2s predicted vs 32.4s measured — consistent
  (plus loop overhead). The model is linear per-call tax; kill the tax, don't
  just parallelize it.

## Dissection — where the 1460ms goes (VAL: profiled, not guessed)

`dissect_t1.py` + cProfile on ONE real `registry.dispatch("read_file")`:

| layer | ms |
|---|---|
| L0 full dispatch | 1710 |
| L3 raw read + line render (`open().read()` + numbering) | 0.25 |
| L5 redact scan | 0.1 |
| L2 extractable-doc probe | 0.0 |
| L1 path resolve | 0.01 |
| L6 json envelope | 0.01 |
| **unaccounted = the tax** | **~1709** |

Profile names the tax (`dissect_profile.txt`):
```
file_operations.py:1507(read_file) ............ 1.191s
file_operations.py:969(_exec) x4 .............. 1.190s
environments/base.py:1445(execute) x4 ......... 1.190s
agent/deadline.py:473(run_bounded_sync) x4 .... 1.188s
threading.py wait x12 / lock acquire .......... 1.187s
```

Root cause: **every local `read_file` runs 3 shell commands**
(`stat` probe + `head|base64` binary sample + `sed|cut` page read, +1 more
from the sample path) — each through `env.execute()` -> `_run_bash`
(process spawn) + `_wait_for_process` (poll loop) + `run_bounded_sync`
(extra thread + Event wait). On Windows/git-bash each spawn+wrap costs
~300ms. 4 x ~300ms = 1.2s. The actual bytes cost 0.25ms.

This is backend-neutrality tax: file ops go through the terminal shell so
remote/docker/modal backends work, and the local backend pays the remote
price on every call. Same shape almost surely holds for search (rg spawn)
and terminal (spawn by definition — but echo at 287ms says the WRAP, not
the command, dominates).

## Prototype direction (no live-tree edits)
1. **Local fast lane**: when backend is local, do file I/O in-process
   (`open()`/`os.stat`/pure-python binary sniff) — same guards, zero spawns.
2. **Persistent pool**: one DaemonThreadPoolExecutor per process for batches,
   not per-batch construction.
3. **Session file cache**: mtime-keyed content cache per session (extends the
   existing dedup-stub idea: stub=8ms proves caching is accepted) — hits
   return rendered content without re-read.
4. Keep: dedup/stub semantics, redaction, read-tracker, path guards.

## Prototype results — same workload, toolrush.py fast lane (VAL: measured)

| check | prototype | baseline | verdict |
|---|---|---|---|
| P0 output parity (content lines, total_lines, file_size) | identical (incl. harness `51|` phantom-line quirk, documented) | — | PASS, byte-parity honest |
| P1 single read dispatch | 1.18ms med / 1.64 p90 | 1459.87ms | **1237x** (stretch goal was 15x) |
| P2 batch 20x (T2-equivalent) | 2.8ms | 32436.4ms | **11584x** (contract needed 3x) |
| P3 cached re-read batch | 3.4ms | — | cache hit ≈ fresh (mtime stat dominates) |
| P4 mtime invalidation | re-read, no stale serve | — | PASS |

What did it: one in-process `open()` replacing up to 5 shell round-trips per
read + persistent daemon pool + mtime-keyed session cache. Zero live-tree
edits — all in `wirebench/toolrush/`.

## Target for the prototype (VAL-SPEED-01: >=3x on batch workload)
- Batch workload = T2-equivalent (20 distinct reads) must go 32.4s -> <=10.8s.
- Stretch: per-call dispatch tax 1460ms -> <100ms (15x) via persistent pool +
  session file cache + trimmed per-call pipeline.
