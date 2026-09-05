# ToolRush reconstruction — implementation design

## Direct operator requirements
- Session `dev-session-1`, user message `481546`: solve architectural tool-call slowness so fast models are not held back by tools.
- Same session, user `489745`: move the bottleneck back to model tokens/sec, not tool calls/file lookups.
- Session `dev-session-3`, user `546047`: maximize parallel calls **without reducing quality**.
- Session `dev-session-2`, user `523063`: keep ToolRush available through updates.

## Measured current state
Fresh-process Python profiles at findings-baseline.json (7 samples per case, first shown separately): real read_file handler ~257ms warm vs upstream native reader ~1.16ms; real shell-rg handler ~287ms vs raw native rg ~14ms; old Python walk ~7.9ms on a narrow glob. These are local operation timings, not model-inclusive turn times. Therefore preserving mature rg semantics costs a few milliseconds versus the incorrect Python shortcut and removes hundreds versus shell transport.

Original Python search is not equivalent to rg: skips ignore semantics, different regex grammar, Windows-only output separators even on POSIX, reads unbounded lines, byte budget counts only sniff bytes. Do NOT expand that engine or cache its incorrect outputs.

## Architecture
1. **Accelerate execution substrate, not semantics.** Extend existing bounded upstream native read implementation to unambiguously mapped local Windows paths. Reuse read assembly, binary handling, path/access guards, and document routing. Unsupported MSYS namespace paths remain on shell fallback.
2. **Native ripgrep transport.** Keep ripgrep (ignore files, regex, encoding, traversal, contexts) and the existing parser/envelope. Replace shell + wrappers + head with direct argv subprocess ONLY on known LocalEnvironment. Bounded prefix collector, cancel/deadline, real exit/error, sanitized env, hidden Windows process. No shell-language reinterpretation; structured argv constructed by existing search methods. No result cache or speculative stale reads. Remote backends retain prior code.
3. **Single result pipeline.** Remove early-return Python search branch; shared page guard/redaction/envelope for all engines. Per-call memo of file guard verdicts eliminates redundant checks without cross-call permission cache.
4. **Work-conserving safe scheduling.** Subject to audit: reuse resource declarations/guards and optimize only dependency-proven ready work. Unknown tools/state mutations remain barriers. No invented tool calls, speculative writes, unlimited workers, or premature execution of incomplete streamed args.
5. **Programmatic batching must function.** Investigate/fix execute_code structured-result decoding for real tool outputs with appended hints so one model turn can complete a mechanical pipeline reliably. Existing tool surface; no new core tools or prompt churn.
6. **Durable release bundle.** Keep source deltas, preimage hashes, tests, benchmark and safe update check/apply tooling outside installed checkout. Drift check must fail closed; never silently patch a changed upstream or auto-restart live agents.

## Baseline/readiness
Main focused pre-change gate: 68/68 (toolrush search + parallel terminal/wire + segmentation), exit 0. Broad file/search inventory additionally ran before implementation: baseline/files-run.json and files.xml contain pre-existing failures and Windows-incompatible assumptions (POSIX permissions, /tmp paths, WSL bash fake, mkfifo/AF_UNIX). This broad suite is **not green**. Atomic prerequisite BASE-WINDOWS: record exact failing/skipped node sets and separate compatibility defects from changed boundaries; use fixed Windows-native real-entry-point contract tests and compare broad failure sets, not pretend the unsupported tests passed. No changes to unrelated product code to appease platform-specific mocks.

## Explicit non-goals
No claiming arbitrary network tools become instantaneous, no artificial TPS benchmark, no live model spend. Do not import lab artifacts into production. No process-wide arbitrary-shell reuse that leaks session state. No automatic provider settings changes. No restart during active runs. Update survival means verified drift-aware packaging, not a promise that arbitrary upstream revisions can be patched blindly.
