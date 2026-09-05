# ToolRush intent — verified reconstruction

The operator wants fast models limited by useful reasoning/token generation rather than harness latency. Direct transcript evidence read by parent:

- `dev-session-1`, message **481546**: "solve the bottleneck of how slow tools calls are ... not setup to properly take advantage of super fast ai models ... solve how tool calls work architecutally and invent a better system".
- Same session, message **481563**: "do whatever it takes to create, optimize, perfect this tech ... bottleneck goes back to a models tokens per second and not stupid tool calls, file lookups etc". **Correction to the research child:** this quote is message 481563, not 489745; raw session scroll verified it.
- `dev-session-3`, message **546047**: "reduce latency ... without reducing quality ... tool calls and how many can be used at once in parralel ... Maximize the parral tool calls ... my fast models can ACTUALLY BE FAST".
- `dev-session-2`, message **523063** (research transcript citation): keep ToolRush "live always even trhough updates". Prior private GitHub instruction is historical authorization, not permission for a new external push in this task.

## Design interpretation, not invented user law
ToolRush is an execution acceleration layer, not a replacement model or a toy search tool. Optimize all three axes: per-operation latency, safe independent-operation throughput, and reliable integration/durability. Preserve tool results, errors, access controls, cancellation and ordered writes. Explicitly report unsupported paths rather than fake acceleration. Never use fixture-only timing as an end-to-end model speed claim.

## Reconstructed deliverable
- Native local data-plane execution, shared semantics and safety pipeline.
- Explicit programmatic parallel read batches in the actual RPC path.
- Conservative native-batch scheduling proof, including malicious/misclassified writes.
- Correct stateful terminal plugin behavior; remove unsafe latency shortcuts.
- Repeatable benchmarks/negative controls and version-aware update protection.

## Claim corrections discovered during work
The initial 257ms read / 287ms search measurements are **bare-process stock transport** baselines; the user plugin is not auto-imported by simple test imports. They cannot be presented as the user's measured running gateway latency. Final comparisons must explicitly include the loaded prechange plugin, current plugin, and stock path. No paid provider calls or running gateway restart were authorized/performed.
