# Validation Contract — Tool-Call Latency Kill (WAVE 3: search tax)

Standing goal: bottleneck back to model TPS, not tool calls.

Wave 1 (DONE): read_file 1460ms -> 1.18ms (1237x), batch 32.4s -> 2.8ms.
Wave 2 (DONE): terminal echo 285ms -> 12.1ms (23.6x) via persistent shell.
Wave-1 T4 measured search at 810ms/call (rg spawn + result shaping per call).

## Scope rules (Operator hard laws respected)
- NO edits to the live hermes-agent tree until a prototype wins in the lab.
- All wave-3 work lives in `C:\dev\toolrush\` (promoted from scratch;
  wirebench/toolrush/ holds wave 1-2 originals).

## VAL- assertions (expect(6))

- VAL-S1: baseline bench drives the REAL search handler (registry.dispatch,
  fixed pattern over a fixed scratch tree) N times, prints per-call ms.
  Target: reproduce ~800ms/call from wave-1 T4. [executable]
- VAL-S2: dissection names the per-call layers (rg spawn, result shaping,
  wrap/deadline, dispatch) with timings — profiled, not guessed. [executable]
- VAL-S3: prototype fast search exists in the lab (toolrush_search.py):
  in-process walk + regex, zero spawns, same result contract
  (path:line:content rows). [executable]
- VAL-S4: prototype re-runs the VAL-S1 workload: >=5x faster per call with
  identical match SETS vs the harness path (compare via comm, not counts).
  [executable]
- VAL-S5: negative control — prototype shelling out to rg per call measures
  ~= baseline; proves the win is in-process search, not the bench. [executable]
- VAL-S6: live hermes-agent tree untouched — `git status --short` shows zero
  NEW modifications vs wave-2 end. [executable]

## Done definition
DONE = all 6 VAL rows evidenced with real command output. No invented numbers.
