# ToolRush final reviewer — report (fresh context)

Writer lane: native read/search + scheduler admission.
Reviewer: fresh context. **Read-only on prod code** — all artifacts confined to this dir
(`.operator/toolrush-v2/reviewer-final/`). No prod file was modified by this reviewer.
Contract: `C:/dev/.operator/toolrush-v2/validation-contract.md` (gates VAL-04/05/06 apply here).
Scope: `tools/toolrush_rg.py`, `tools/toolrush_runtime.py`, native paths in
`tools/file_operations.py` / `tools/file_tools.py`, `agent/toolrush_admission.py`,
helper gating in `agent/tool_dispatch_helpers.py`.

## Verdict summary

| Area | Verdict | Evidence (runnable, exit 0) |
|---|---|---|
| `toolrush_rg.py` capture loop (bounds/budget/timeout/error honesty) | **PASS** | `repro_core.py` (19/19), `repro_timeout.py` |
| native read parity (`_read_file_native` vs shell) | **PASS** | `repro_core.py` (9 parity cases) |
| native rg search parity (ignore/config/regex/sort) | **PASS** (1 note, F4) | `repro_core.py`, probe probes in report |
| `toolrush_runtime.py` gate | **PASS** | `repro_core.py` on/off toggles |
| `toolrush_admission.py` readonly gate | **PASS** | `repro_admission.py` (93/93) |
| `tool_dispatch_helpers.py` admission drift | **PASS** | `repro_drift.py` (0 drift cases) |

Overall: **no correctness or security regression found in the native read/search or
admission paths reviewed.** One minor consistency note (F4/CRLF), no reproducible defect.

## Repro commands (all verified this session)

```
cd C:/dev/.operator/toolrush-v2/reviewer-final
python repro_core.py        # exit 0 — 19/19 boundary tests
python repro_timeout.py     # exit 0 — deterministic rg timeout: reaped, reason=search_timeout
python repro_admission.py   # exit 0 — 93/93 admission fuzz cases
python repro_drift.py       # exit 0 — 0 helper-vs-base permissiveness drifts
```

## What the boundary tests cover (evidence)

**rg bounds (`repro_core.py`, `repro_timeout.py`)**
- `run_rg --files` over a synthetic tree: output bounded to `max_lines` (2-line tree
  returned 2 lines; 5-line cap honored at n=5).
- Byte budget: `--max-filesize`-style cap triggers `reason=search_output_budget`,
  `exit=1`, `limited=True` — the "honest pagination" invariant holds (a truncated
  result never presents as complete).
- Timeout: deterministic 2s hang (`rg -f patternfile` over huge tree, 1s timeout)
  → process reaped, `reason=search_timeout`, `exit=124`, bytes=0. No orphan process
  leak observed (wait completed at dt=2.00s).
- Error honesty: rg exit 2 propagates with `limited=False`, no fake "bounded" claim.

**Native read parity (`repro_core.py`)**
- Native vs shell byte-identical for: mid-file page (463B), `total_lines` (300/300),
  end-of-file sentinel line, beyond-EOF (empty), zero-byte file, file with no trailing
  newline (last line returned, no spurious `truncated` flag/hint), long-line clamp
  (2123B both), binary file (flagged on both paths), directory (both reject with
  "not a regular file").

**Native search parity**
- Node_modules ignored, sort order, line-number/content parity between
  fast_search enabled/disabled on multi-file trees.

**Admission (`repro_admission.py` — 93 cases, all PASS)**
- Rejects: all redirect forms (`>`, `>>`, `<`, `2>&1`), heredocs, backticks,
  `$(...)`, `${!x}`/`${x:=y}`, background `&`, `&&` chains with writes, pipes to
  `tee`/`sh`, brace groups, subshells, unknown binaries, `python -c`, `node -e`,
  `npm run`, `pip install`, `uv run`, `curl -o/-T/-X/-K`, `sed -i`, `git push/commit/
  clean/checkout/config-write/--ext-diff/--textconv/--exec-path/--output`,
  `rg --pre/--hostname-bin`, `sort -o/--compress-program/-T`, `uniq in out`,
  `jq -L/--run-tests`, `xargs`, `find`, `awk`, `chmod/mkdir/rm`, env assignment
  prefixes, newline-separated multi-commands, `env/nohup/timeout` wrappers,
  `printf -v`.
- Admits (read-only sanity kept): `cat/grep/ls/rg/git status|log|diff|branch|
  config --get|ls-files`, safe `curl` GET forms, `sed -n 'Np'`, `sort/uniq/jq/date/
  hostname/wc/ps/md5sum`, pipelines of reads, `printf`, `echo *` glob, `ls ~`.

**Admission drift (`repro_drift.py`)**
- `_is_readonly_terminal_command` (helper layer) is never more permissive than
  `toolrush_admission.readonly` across the full fuzz set — 0 drift cases.

## Notes (non-blocking)

### F4 (minor, consistency — CRLF residue in shell-search content, not native)
Shell-transport search content can retain a trailing `\r` on CRLF files, while the
native path strips it (observed in instrumented probes: `'def hello():\r'` via shell
pipeline parse vs `'def hello():'` via native argv run of the same file). Both paths
agree on Windows-created text files in the standard parity cases because rg itself
emits `\r` only for files whose bytes contain it and the native runner normalizes.
Impact is cosmetic-to-minor (a `\r` at end of a matched line can confuse exact-match
post-processing by the model); **not** a regression introduced by the native path —
the native path is the *cleaner* of the two. Recommend a follow-up `\r`-strip in the
shell-stdout match parser for uniformity. No action taken (read-only constraint).

### F1 (benign, previously noted)
`toolrush_rg.py` row-bound `line_count` accounting on the final chunk has no
observable effect — verified by exact line counts (`max_lines=5` over a 30-line file
returns exactly 5 lines).

### F2 / F3 (previously probed, confirmed non-issues)
`total_count` honesty under native reads and the `_is_image` gate ordering across
path spellings both verified with no divergence between enabled/disabled modes.

## Scope discipline

- No prod file modified (git status shows only writer-lane changes, none authored
  here; this reviewer's writes are exclusively `report.md` + `repro_*.py` in this dir).
- No broad test suite run; no background tools/loops; no git operations beyond status.
