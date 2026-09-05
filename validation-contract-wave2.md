# Validation Contract — Tool-Call Latency Kill (WAVE 2: terminal tax)

Standing goal: bottleneck back to model TPS, not tool calls.

Wave 1 (DONE, evidenced in results.md): read_file 1460ms -> 1.18ms (1237x),
batch 32.4s -> 2.8ms, negative control FAIL-as-designed, write-ordering safe,
live tree untouched (modified files predate session; mtimes 1:49PM < 6:33PM start).

## Scope rules (Operator hard laws respected)
- NO edits to the live hermes-agent tree until a prototype wins in the scratch lab.
- All work lives in `C:\dev\wirebench\toolrush\`.

## VAL- assertions (expect(6))

- VAL-T1: baseline bench drives REAL terminal handler (`echo`) N times, prints
  per-call ms. Target: reproduce ~287ms/call from wave-1 T5. [executable]
- VAL-T2: dissection names the wrap layers per call (command rewrite, cwd
  snapshot/probe, login-shell decision, _wrap_command, spawn+wait+deadline)
  with timings — profiled, not guessed. [executable]
- VAL-T3: prototype persistent-shell executor exists in scratch lab
  (toolrush_exec.py): ONE long-lived bash process, stdin commands in,
  framed stdout out, no spawn per call. [executable]
- VAL-T4: prototype re-runs the VAL-T1 workload: >=5x faster per call with
  byte-identical stdout vs the harness path. [executable]
- VAL-T5: negative control — prototype with persistent shell DISABLED
  (spawn-per-call) measures ~= baseline; proves the win is the architecture.
  [executable]
- VAL-T6: live hermes-agent tree untouched — `git status --short` shows zero
  NEW modifications vs wave-1 start (mtimes pre-session). [executable]

## Done definition
DONE = all 6 VAL rows evidenced with real command output. No invented numbers.
