# Validation Contract — Tool-Call Latency Kill (WAVE 4: dispatch pipeline)

Standing goal: bottleneck back to model TPS, not tool calls.

Wave 1 (DONE): read_file 1460ms -> 1.18ms (1237x), batch 32.4s -> 2.8ms.
Wave 2 (DONE): terminal echo 285ms -> 12.1ms (23.6x) via persistent shell.
Wave 3 (DONE): search 900ms -> 42ms (21.3x), sets identical 40/40.
Waves 1-3 killed per-HANDLER taxes. What remains under every call is the
dispatch pipeline ABOVE the handler: executor routing, dispatch helpers,
middleware/tracker bookkeeping, result normalization + truncation.

## Scope rules (Operator hard laws respected)
- NO edits to the live hermes-agent tree until a prototype wins in the lab.
- Live tree has sibling toolcap WIP (prompt_builder/dispatch_helpers/
  executor/run_agent modified) — read-only for us, never touch, never stash.
- All wave-4 work lives in `C:\dev\toolrush\`.

## VAL- assertions (expect(5))

- VAL-D1: bench drives a TRIVIAL handler (no-op returning fixed string)
  through (a) raw direct call and (b) REAL registry.dispatch, N times each.
  Prints both per-call medians. The delta = registry-layer tax, isolated
  from all handler work. [executable]
- VAL-D2: cProfile dissection of one REAL dispatch of the trivial handler
  names the layers (entry lookup, async bridge check, normalize, error
  wrap) with timings — profiled, not guessed. [executable]
- VAL-D3: bench drives the trivial handler through the FULL agent-loop
  path (tool_executor entry, same as a model tool call would take) vs raw
  registry.dispatch. The delta = executor-pipeline tax above the registry.
  [executable]
- VAL-D4: verdict with numbers: EITHER a prototype fast-dispatch that beats
  the full path >=3x with identical results, OR a measured finding that the
  pipeline tax is <10% of a real fast-handler call (toolrush read 1.18ms)
  making further dispatch work pointless — with the numbers proving it.
  No optimization theater: if the tax is negligible, say so and stop. [executable]
- VAL-D5: live hermes-agent tree untouched — `git status --short` shows zero
  NEW modifications vs wave-3 end (sibling toolcap files predate us). [executable]

## Done definition
DONE = all 5 VAL rows evidenced with real command output. No invented numbers.
A documented "tax is negligible, stop here" is a valid DONE for VAL-D4.
