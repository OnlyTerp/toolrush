# ToolRush v2

**Purpose:** make fast models wait for useful computation, not avoidable tool machinery. One semantic implementation, multiple low-overhead transports, explicit safe concurrency.

## What runs
- Native Windows/local bounded file reader through the normal `read_file` handler. No result cache added.
- Native `rg.exe` argv transport; real ripgrep ignore/regex rules, same renderer/guards/redaction, bounded output and cancellation.
- Streaming persistent Windows Bash broker; current filtered environment per frame, state committed atomically **before** completion, true exit codes, no hidden output cap, child-tree cancellation. Unsupported/busy/background paths use stock transport.
- `execute_code` local RPC `parallel(...)`: 1–16 read requests, ≤4 workers, input-order results, enabled-tool intersection, atomic budget reservation, authentication, current-cell context, no writes/terminal. Existing segmented model-tool scheduler stays intact; terminal admission tightened.
- Strict JSON search envelopes; stable content-search pagination plus honest has-more metadata.

## Use
After a **fresh gateway process** has loaded v2:
```python
from hermes_tools import parallel
results = parallel([
    {"tool": "read_file", "args": {"path": "C:/project/README.md"}},
    {"tool": "search_files", "args": {"pattern": "TODO", "path": "C:/project"}},
])
print(results)
```
Only independent reads belong in a batch. Tiny already-fast reads can be slower in threads; don't force batching for one or two trivial operations. Sequential client calls and arbitrary ThreadPoolExecutor use of the old shared client are not magically parallelized.

## Activation
Plugin remains in the default profile's enabled plugins. All tests and fresh-process smoke use installed code. **Already-running gateway/session processes have not been restarted or hot-patched.** When sessions are idle, restart the gateway manually from the desktop or an external terminal. A new chat in the same old gateway is not sufficient.

```bash
# Read-only, no model requests
C:/dev/AppData/Local/hermes/hermes-agent/.venv/Scripts/python.exe C:/dev/AppData/Local/hermes/plugins/toolrush/doctor.py --smoke
```

## Runtime rollback (preferred)
Set in the default profile's config then start a fresh gateway:
```yaml
toolrush:
  enabled: false
```
Per-lane config: `fast_read`, `fast_search`, `warm_shell`, `parallel_reads`.
Equivalent environment gates: `TOOLRUSH_FASTLANE=0`, `TOOLRUSH_SEARCH=0`, `TOOLRUSH_PERSIST=0`, `TOOLRUSH_PARALLEL=0`. `HERMES_NATIVE_FILE_READ=0` is still honored. Disabling an optimization never disables safety checks; search correctness fixes remain.

## Source rollback / recovery
Runtime gates are the first rollback because they preserve later unrelated edits. Original source preimages are in `C:/dev/.operator/toolrush-v2/baseline/` and copied into `C:/dev/toolrush/v2/evidence/baseline/`. They cover the modified core modules and original plugin entry point. New helper modules are listed in the bundle manifest.

Do not copy a whole preimage over a module that has since received other work. Stop affected processes when idle, compare the current module with both the preimage and v2 snapshot, and revert only ToolRush-owned changes. Leave the new helper files present until no current code imports them. Do **not** restore the old warm-shell plugin automatically: it contains the state race that v2 fixes. Disable the warm lane instead. No running process is hot-unpatched.

## Update survival
`compat.py` + `payload.json` + `lib/` live outside the upstream checkout. The normal plugin loader verifies payload hashes and compares **only touched function ASTs**, ignoring comments/whitespace. Known-before functions are restored **in memory**; known-after functions are left alone. Existing imported function references stay valid. New functions keep live module globals. A changed touched upstream function causes that entire lane to refuse patching with a `ToolRush ... disabled on changed upstream` warning. Snapshot incompatibility also disables the warm-shell plugin.

This is compatibility-checked persistence, not a promise to override arbitrary future updates. It never rewrites updated upstream files or auto-merges unknown code. Run doctor after updates. Degraded status needs review; do not force a hash or blindly copy old modules back.

## Evidence / reproducibility
`C:/dev/.operator/toolrush-v2/` contains original intent, contract, baseline sources, paired benchmarks, XML test results, negative controls, independent reviews, and update simulation. `simulate_update.py` removes 25 touched functions in an isolated process, restores all four lanes, drives read/search/generated RPC, and proves disk hashes unchanged. No provider benchmark usage or gateway restart.

Full results: `C:/dev/.operator/toolrush-v2/report.md`.
