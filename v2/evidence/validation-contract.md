# ToolRush — reconstruction and performance contract

Scope: recover the operator's original ToolRush intent, audit the installed Hermes tool pipeline, implement and exercise a compatible accelerated path. This contract precedes implementation. Detailed test selectors will be appended after discovery, not retrofitted to make failures pass.

## Definition of done
A working local implementation exercised through real Hermes entry points, with preserved results/safety, reproducible baseline-versus-new measurements, explicit enable/disable behavior, and a safe activation/rollback path. No provider benchmark spend, no gateway restart while sessions run, no public push/deploy, no unrelated profiles modified. A pending restart is not called live activation.

## Required gates — expect(9)
- VAL-INTENT-01 [judgment]: Parent reads original human messages in sequence and writes intent.md citing session/message identifiers, distinguishing direct requirements from design interpretation. No invented feature requirements.
- VAL-BASE-02 [executable]: Capture repository identity/status and run the relevant pre-change tests. Save exact commands, exit codes, and failure node IDs. Do not mask a baseline failure as success.
- VAL-DESIGN-03 [judgment + executable]: Record current critical path and existing alternatives/upstream facilities; profile real local operations before choosing changes. Save structured performance findings and profiler/benchmark artifacts.
- VAL-CORRECT-04 [executable]: New tests drive real tool entry points with acceleration enabled/disabled and assert equivalent outputs/semantics, including pagination, errors, edits between calls, and ordering/dependency cases relevant to changes. All named regression tests must be collected and pass, zero unexpected skips.
- VAL-SAFE-05 [executable]: Secret redaction, access/path guards, command approvals, cancellation, resource bounds, and backend isolation remain effective. Test changed boundaries and fail closed on unsupported optimizations.
- VAL-NEG-06 [executable]: A disposable negative control disables each claimed core improvement or injects a defect and makes its proving assertion fail. Restore/verify by hashes; never disrupt the installed live process or overwrite sibling work.
- VAL-PERF-07 [executable]: Repeated paired baseline/new benchmarks through real entry points on real repository files plus clearly labeled controlled test fixtures. Report sample counts, cold/warm distinction, medians/p95, costs and regressions. Require measured gains on chosen target workloads; do not generalize microbenchmarks to model/network latency.
- VAL-INTEGRATE-08 [executable]: Relevant broader regression suites pass or unchanged baseline failure SETS are documented. Fresh-process entry-point smoke exercises installed code, not merely an imported isolated helper. Preserve a kill switch and record activation state.
- VAL-DELIVER-09 [judgment + executable]: Fresh-context review of the contract/diff/artifacts, fixes for demonstrated issues, durable usage/rollback/runbook and final report linked to real evidence. State remaining limits precisely.

## Evidence layout
- intent.md — original human intent, design interpretation, scope
- inventory.json / baseline/ — paths, hashes, git state and original behavior
- findings.json — structured measured performance/correctness findings
- design.md — implementation architecture and alternatives
- evidence/ — command logs, pytest XML/JSON, benchmark raw samples and summaries
- report.md — per-VAL verdict and rollout/rollback

## Execution discipline
One writer, one shared branch; no stash/reset/checkout or commits of unrelated changes. Read-only delegates may inspect disjoint lanes; every delegate reports summary, left-undone, commands+exit codes, files touched. Unexpected gate failure gets one named atomic fix followed by targeted revalidation. Blocking credentials/environment gets one honest attempt then a documented pivot, not a retry loop.
