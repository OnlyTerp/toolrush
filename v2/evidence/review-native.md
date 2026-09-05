# ToolRush native rg transport + Windows reader — fresh-context review (reviewer lane)

Reviewer: fresh-context subagent, read-only, no repo edits, no paid models, no restarts.
Scope: tools/toolrush_rg.py, toolrush_runtime.py, file_operations.py (native read + native rg), file_tools.py (bridge removal), approval.py (fast-path gating), environments/base.py + local.py (snapshot env interpretation), tests/tools/test_toolrush_native_*.py.
Review window: 2026-09-04 ~16:45–17:35 EDT, against the tree as it evolved mid-review (parent landed sentinel-honesty, sort=path, CRLF normalization, unterminated-line fix, zero-match probes while I read). Items marked [fixed-mid-review] were demonstrated broken earlier and re-verified fixed in the final tree I read.

## Blockers / highest-impact findings

### B1 — VAL-SAFE-05: snapshot env-dump parser fails OPEN on exclusion-refresh errors (cross-profile secret persistence)
File: tools/environments/base.py:695–723 (`_snapshot_excluded_passthrough_names`), consumed at base.py:771→775 (bootstrap) and 974–980 (per-command re-dump).

Demonstrated by code reading (not yet fault-injected — see repro): the exclusion set is computed inside `try:` and ANY failure (`is_multiplex_active()` raising, `tools.env_passthrough` import failure, odd name types) is swallowed to `logger.debug` and returns whatever was accumulated — empty on the first dump. The dump then runs with `extra_unset=""`: `export -p` writes the full child env, including profile-scoped passthrough names (BUZZ_* and any configured passthrough) into `hermes-snap-<id>.sh`. A later command from a different profile sharing the collapsed LocalEnvironment sources that snapshot — the exact cross-profile leak local.py:1972–2004 documents for BUZZ_*. The monotonic-set design only protects if the refresh SUCCEEDS at least once; fail-open on first dump defeats it.

This is the concrete edge behind the parent's "snapshot export parser has shell env edge cases" concern, minus HOME/PATH: HOME/PATH persistence is by design (session continuity), and unconditional unsetting would break sessions — do not do that. The demonstrated defect is the fail-open, not the persisted names themselves.

Exact runnable reproduction (venv, no pipes; expected: snapshot contains BUZZ_TEST_TOKEN → proves fail-open):
```
cd C:/dev/AppData/Local/hermes/hermes-agent
.venv/Scripts/python -c "import sys; sys.path.insert(0,'.'); import os; os.environ['BUZZ_TEST_TOKEN']='x'; import tools.environments.base as b; from unittest.mock import patch; import agent.secret_scope as ss; env=b.BaseEnvironment.__new__(b.BaseEnvironment); env._profile_scoped_passthrough=True; env._snapshot_passthrough_names=set();
with patch.object(ss,'is_multiplex_active',side_effect=RuntimeError('boom')):
    print('excluded set =', env._snapshot_excluded_passthrough_names())
assert env._snapshot_excluded_passthrough_names()==()"
```

Exact repair (fail closed — skip the re-dump rather than dump unfiltered):
- base.py `_snapshot_excluded_passthrough_names`: replace the bare `except Exception: logger.debug(...)` with a monotonic fail-closed marker, e.g. set `self._snapshot_exclusion_broken = True` on exception; return value unchanged.
- base.py `_build_wrapped_command` (the `if self._snapshot_ready:` block, ~line 974) and `init_session` bootstrap (~line 771): when `self._snapshot_exclusion_broken`, skip generating `_export_dump_excluding_session_vars` entirely (leave the previous good snapshot in place) and log at WARNING. A stale-but-previously-filtered snapshot is safe; an unfiltered one is not.
- Belt: in `_export_dump_excluding_session_vars`, additionally hard-unset names matching the known secret prefixes even when `excluded_names` is empty — cheap, and keeps the file clean if a caller forgets to pass the set.

Severity: high (conditional — requires multiplex active or import failure at exactly snapshot time; blast radius is cross-profile secret read on shared env instances).

### B2 — VAL-SAFE-05 [verified-good, keep guards]: native fast paths preserve the security gates I could exercise
Positive results, recorded because the contract requires testing the changed boundaries:
- Approval/blocklist ordering intact: file_tools.py:1674–1687 runs `_is_blocked_device` (pure path check) and the FIFO guard BEFORE `ops.read_file`, so the native lane cannot bypass the device/FIFO denial.
- `_read_file_native` (file_operations.py:1902+) uses `os.stat` + `S_ISREG` (stat-not-open), refuses non-regular files via `_not_regular_error`, and does the 1000-byte binary sample before any page decode — no new binary/FIFO hole.
- Remote isolation: `_local_native_path` (1865+) returns None unless `self._lsp_local_only()`; refuses `/tmp`, `/etc`, `/dev`, drive-relative, and `\\?\`/`\\.\` namespaces; UNC is admitted but only ever on local-only backends. `_native_read_enabled` additionally requires `enabled('fast_read','TOOLRUSH_FASTLANE')` and HERMES_NATIVE_FILE_READ kill switch. No remote-path resolution on controller found.
- Shell-arg handling: `_escape_native_tool_arg` (1426+) maps MSYS→forward-slash Windows form and POSIX-quotes; `_quote_executable` (1225+) special-cases LocalEnvironment. No injection path demonstrated with quoted args containing spaces/quotes.

## Fixed-mid-review items (demonstrated broken earlier, re-verified fixed)
- VAL-CORRECT-04: rg default match order was directory-walk order (native lane returned d7→d0 while shell lane returned d0→d7 in my early probe; page overlap proved unstable pagination). Parent added `--sort=path` to both lanes (file_operations.py:4152 shell cmd, 4222 argv). Differential now stable.
- VAL-CORRECT-04: CRLF files decoded differently (native lane kept `\r` artifacts pre-fix). Native now does `.replace('\r\n','\n')` on the assembled page (file_operations.py ~2015), matching shell output. `test_engine_envelope_differential` CRLF case passes.
- Sentinel honesty: `total_count_is_lower_bound` (file_operations.py:444) + honest has-more for the sentinel row — matches the `head -n` overshoot semantics I confirmed (fetch_limit = limit + offset overshoots intentionally; clamped per-match by --max-columns per the cline#13525 port comment at 4153+).

## Verified test state (executed, no output pipes masking exit codes)
- `python -m pytest tests/tools/test_toolrush_native_read.py` → 29 passed (18.38s), exit 0.
- Both native files, full runs ×2 → 50 passed (39.87s / 40.32s), exit 0 both.
- One transient failure observed mid-review (`test_engine_envelope_differential[kwargs10]`, then `test_guard_after_window` in the older tree) self-resolved after parent's CRLF/sentinel fixes landed; isolated re-run 14/14 passed. Not flaky in final tree across 3 runs.
- Known parent-owned item I did NOT treat as reviewer failure: target=files discovery-order array instability vs legacy byte-stable contract — parent is switching comparisons to set equality; my runs confirm arrays-not-sets divergence exists between lanes without sort applied.

## Notes (non-blockers, for the record)
- Native read loop has no in-loop interrupt check (runs to EOF counting lines). Not a regression: the old shell path also fully counted lines via `wc -l` and was only killable at process granularity. If later desired: check `tool_interrupt.is_interrupted()` per 1 MiB chunk and bail to the shell path.
- `_quote_executable`'s non-local POSIX fallback (`'...'` quoting) would be wrong for a remote Windows shell, but no remote-Windows backend in scope; noting for future.
- Did not re-audit approval.py's final 147-line diff after the last parent write (read the earlier version only). Flag for VAL-DELIVER-09 fresh review if approval.py changed after 17:20 EDT.

## Left undone
- No fault-injection execution of B1 (code-reading demonstration only; repro command provided).
- approval.py final-diff re-read, multi-line `alias -p` snapshot edge, native-loop interrupt check — all explicitly out of the narrowed scope the parent set.
