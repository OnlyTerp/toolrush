# Validation Contract — Tool-Call Latency Kill

Goal: make harness tool-call latency so small the bottleneck returns to model TPS, not dispatch/file/lookup overhead.

## Scope rules (Operator hard laws respected)
- NO edits to the live hermes-agent tree until a prototype wins in the scratch lab.
- Live tree is dirty (`git status`: modified prompt_builder/tool_dispatch_helpers/tool_executor/run_agent + .bak files) and 743 behind origin — we do NOT touch it.
- All prototype + benchmark work lives in `C:\dev\wirebench\toolrush\`.

## VAL- assertions (expect(8))

- VAL-BASE-01: baseline bench script drives the REAL `registry.dispatch` + REAL file/terminal tool handlers (no mocks) and prints per-op ms + batch timings. [executable]
- VAL-BASE-02: baseline shows the batch tax breakdown: sequential N×read_file vs concurrent batch vs single dispatch overhead — real numbers, recorded in `results.md`. [executable]
- VAL-PROTO-01: prototype fast-runtime exists in scratch lab: persistent worker pool + session-scoped file cache + batched multi-op tool — driven against REAL files in scratch dir. [executable]
- VAL-PROTO-02: prototype re-runs the SAME workload as VAL-BASE-01 and prints side-by-side ms + speedup factor per op. [executable]
- VAL-SPEED-01: prototype batch workload is ≥3x faster wall-clock than baseline on the same box (or report BLOCKED with the measured floor). [executable]
- VAL-SAFE-01: prototype keeps ordering semantics for writes (parallel reads OK, overlapping writes serialize — proven by a mixed read/write contention test). [executable]
- VAL-NEG-01: negative control — prototype with cache+pool DISABLED measures ≈ baseline (±20%); proves the speedup comes from the architecture, not the test. [executable]
- VAL-NOHARM-02: live hermes-agent tree untouched — `git status --short` shows zero NEW modifications vs start of work. [executable]

## Done definition
DONE = all 8 VAL rows evidenced with real command output. No invented numbers. A PASS with zero checks is not a PASS.
