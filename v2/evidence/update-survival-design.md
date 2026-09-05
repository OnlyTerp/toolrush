# Update survival (VAL-INTEGRATE-08 / VAL-DELIVER-09)

The user's original intent explicitly includes surviving Hermes updates. Core source edits alone do not satisfy it.

Implementation: persist ToolRush helpers plus a function-level compatibility payload in the existing user plugin (outside Hermes git). At plugin load, compare AST fingerprints for the small touched functions against known pre/post versions; atomically preflight each dependent lane before applying any in-memory changes. Load helper modules only from hash-verified payloads. Known compatible updates restore the lane in memory; unknown upstream changes leave that lane on upstream behavior and emit an explicit degraded warning. Never overwrite updated files or pin the whole old module. Bound functions preserve references by updating function code/defaults in place. No gateway restart performed.

Tests first: fake modules validate exact-before apply, exact-after no-op, AST-equivalent whitespace accepted, unrelated module edits preserved, target-function drift refused before mutation, helpers hash mismatch refused. Real update simulation removes this turn's touched functions in a disposable process using baseline function payloads, invokes plugin compatibility loader, and drives real read/search/execute_code. Hash all installed files before/after; no source writes. Repeated registration must be idempotent.

This protects known compatibility, NOT an unqualified promise against arbitrary future breaking changes. Unknown schema/signature changes must require review, not unsafe auto-merge.
