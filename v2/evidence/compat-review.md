# Compat loader narrow review — update-survival (fresh reviewer, 2026-09-04)

Scope: `plugins/toolrush/compat.py`, `__init__.py` register, `payload.json`, `tests/tools/test_toolrush_update_survival.py`, contract + update-survival-design. Review only; no production edits.

## Verdict: NO demonstrated blockers

## Evidence (real probes, this session)

| # | Probe | Result |
|---|-------|--------|
| E1 | pytest `tests/tools/test_toolrush_update_survival.py` | 4/4 pass, exit 0 (incl. parent's new live-globals test) |
| E2 | LOAD_GLOBAL scan of every payload `after` (incl. nested code objects) against live upstream module dicts + builtins | all names resolvable — no lost globals in any patched function |
| E3 | Real `register()` → `install()` → all 4 lanes `ready` (files/rpc/admission/snapshot) | pass |
| E4 | Full `LocalEnvironment` boot through patched `Local._run_bash` (WarmHandle): snapshot init, `echo WARMTEST-$((6*7))` → `WARMTEST-42`, second command reuses warm shell, `env.cleanup()` clean | pass |
| E5 | Idempotency: `install_rows` twice → patched 1 then 0, original function reference preserved | pass |
| E6 | New function (`before:null`) binds live `module.__dict__`; late global mutation visible | pass (parent fix confirmed) |
| E7 | Lane isolation: failing lane degrades without corrupting already-patched lane | pass |
| E8 | Boot recursion: `tools.environments.base` import chain imports only `hermes_cli._subprocess_compat`; `hermes_cli/__init__` and plugin machinery never re-enter during base import; `hermes_cli.config` imports standalone | no recursion path |
| E9 | `simulate_update.py` (parent) | passes; file hashes unchanged pre/post |

## Checked specifically for the four requested classes

- **Stale semantics**: `matches()` = digest fast-path → `inspect.getsource` AST digest → bytecode fingerprint fallback. Fingerprint ignores filenames/line offsets only; semantics-bearing fields (names, args, consts, exception table) compared. `_run_bash` wrapper signature matches upstream `_run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None)` exactly; all base.py call sites pass keywords that match. WarmHandle covers the ProcessHandle duck-type (pid/poll/wait/kill/returncode/stdout).
- **Lost globals**: in-place `__code__` swap keeps `current.__globals__` = live module dict. New functions rebound via `types.FunctionType(..., module.__dict__)` (parent's fix, E6). All `LOAD_GLOBAL` names verified present in live upstream modules (E2).
- **Unsafe partial patch**: `install_rows` fully preflights the lane (`prepare_rows`) before first mutation; per-lane try/except isolates failures (E7). Helper exec failure pops `sys.modules[name]` on exception.
- **Boot recursion**: no import cycle between plugin loader and `tools.environments.*` (E8); helpers load only via hash-verified plugin files or byte-identical upstream copies; `enabled()` → `hermes_cli.config` is standalone-importable, read-only, no plugin dependency.

## Findings (non-blocking)

1. **LOW — digest fast-path trusts the marker, not the body** (compat.py:63-65). If an external mutator swaps a patched function's code object in place, `matches()` still returns True while the digest attr is set (demonstrated: `matches(before)->True` on a body with `x+99`). Only ToolRush sets these attrs today, so no live path; fingerprint fallback would catch it if attrs were cleared. Repro: set `_toolrush_installed_code`/`_toolrush_source_digest` on a function whose `__code__` was replaced, then re-install.
2. **INFO — bootstrap degradation is all-or-nothing for helpers** (compat.py:114-138). One helper SHA mismatch upstream (e.g. upstream edits its own `tools/toolrush_runtime.py`) raises inside `load_helpers` → `register()` degrades the whole plugin and returns before any lane installs — including lanes that never touch that helper. This is fail-closed per design ("unknown upstream → review"), but coarser than the per-lane degradation the lanes themselves implement. No fix requested in this review.
3. **INFO — upstream now ships its own `tools/toolrush_*.py` files.** `load_helpers`'s `find_spec` branch will hash-verify and adopt the upstream copy; identical bytes = no-op, any drift = whole-bootstrap degraded (see #2). Expected behavior, worth remembering at the next Hermes update.

## Commands (exit codes real)

- `python -m pytest tests/tools/test_toolrush_update_survival.py -q` → 4 passed, exit 0
- `python -m pytest tests/tools/test_toolrush_update_survival.py -v` → 4 passed, exit 0
- probes E2-E9: inline python heredocs through the real repo path, all printed expected sentinels, exit 0

## Files touched

- `.operator/toolrush-v2/compat-review.md` (this file) — only file written.
